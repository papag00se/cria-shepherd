"""Image structure at shared wire/fitting boundaries; no vision-cost guesses."""

def has_images(message: dict) -> bool:
    content = message.get('content') if isinstance(message, dict) else None
    return isinstance(content, list) and any(
        isinstance(part, dict) and part.get('type') in ('image_url', 'input_image')
        for part in content)

import copy
import hashlib
import json
from dataclasses import dataclass
from . import bodykeys,generation,jsontext,prompts

class ImageUnavailable(ValueError):
    """Explicitly unavailable viewing/retention; never a model observation."""
    @property
    def response_error(self):return {'type':'image_unavailable','message':str(self)}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def image_parts(messages):
    return [p for m in messages if isinstance(m,dict) and isinstance(m.get('content'),list)
            for p in m['content'] if isinstance(p,dict) and p.get('type')=='image_url']


@dataclass(frozen=True)
class CoderRoute:
    # Integration must construct this after actual provider selection + role application.
    provider: object
    model: str
    role_signature: str
    vision: bool | None

    def same(self,other):
        return (isinstance(other,CoderRoute) and self.provider is other.provider and
                self.model==other.model and self.role_signature==other.role_signature and self.vision is other.vision)


@dataclass(frozen=True)
class Observation:
    extracted_text: str
    description: str
    uncertainty: str


@dataclass(frozen=True)
class Delivery:
    """Mint only at the actual wire/terminal boundary, not from a harness alias."""
    attempt: str
    provider: object
    model: str
    role_signature: str
    image_digest: str
    completion: dict
    terminal_complete: bool

    @classmethod
    def from_wire(cls,attempt,provider,role_signature,wire,completion,*,terminal_complete):
        messages=wire.get('messages') or []
        images=image_parts(messages)
        user_images=image_parts([m for m in messages if m.get('role')=='user'])
        if len(images)!=1 or user_images!=images:raise ImageUnavailable('Observation wire did not carry exactly one original image')
        return cls(attempt,provider,wire.get('model'),role_signature,digest(images[0]),
                   copy.deepcopy(completion),terminal_complete)


def parse_observation(completion,*,terminal_complete):
    if terminal_complete is not True or not isinstance(completion,dict) or completion.get('error') or generation.incomplete(completion):
        raise ImageUnavailable('Image observation did not complete; original image remains pending')
    choices=completion.get('choices')
    if not isinstance(choices,list) or len(choices)!=1 or choices[0].get('finish_reason')!='stop':
        raise ImageUnavailable('Image observation has no successful terminal completion')
    message=choices[0].get('message') or {}
    if message.get('tool_calls') or message.get('refusal') or message.get('role')!='assistant':
        raise ImageUnavailable('Coder did not return an image observation')
    def unique(pairs):
        out={}
        for key,value in pairs:
            if key in out:raise ValueError('duplicate observation key')
            out[key]=value
        return out
    try:
        # A real gemma4_12b observation arrived as ```json {...}``` and was refused as unreadable.
        # Fences/<think> are framing noise jsontext already owns; the object inside stays strict
        # (exactly the four keys, no duplicates, nothing else on the line).
        content=message.get('content')
        value=json.loads(jsontext.denoise(content).strip() if isinstance(content,str) else content,object_pairs_hook=unique)
    except (TypeError,ValueError) as exc:
        raise ImageUnavailable('Coder image observation was unreadable; original remains pending') from exc
    keys={'viewed','extracted_text','description','uncertainty'}
    if (not isinstance(value,dict) or set(value)!=keys or value['viewed'] is not True or
            any(not isinstance(value[k],str) for k in keys-{'viewed'}) or not value['description'].strip()):
        raise ImageUnavailable('Coder could not establish a usable image observation; original remains pending')
    return Observation(value['extracted_text'],value['description'],value['uncertainty'])


def observation_request(applied_body,route,task,part):
    if route.vision is not True or not route.model or applied_body.get('model')!=route.model:
        raise ImageUnavailable('Selected coder vision capability or actual model is unavailable; original image retained')
    # Copy actual applied coder settings; tool execution is not part of an observation.
    request={k:copy.deepcopy(v) for k,v in applied_body.items() if k not in bodykeys.ALL and
             k not in ('messages','tools','tool_choice','parallel_tool_calls','response_format','stream_options')}
    request['stream']=False
    request['messages']=[{'role':'system','content':prompts.load('image_observe_system')},
                         {'role':'user','content':[{'type':'text','text':prompts.render('image_observe_task',task=task)},copy.deepcopy(part)]}]
    return request
