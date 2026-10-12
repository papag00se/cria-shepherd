"""Scripted judge for validate_compaction_briefing tests.

The plan lens now asks one question PER SENTENCE (PLAN or STATE, then TASK or NEW), so a test can no
longer script "the first call is the retrospective verdict". ``answer`` replies to the sentence lens
by its closed word set and hands every whole-candidate lens (scope, fidelity) the next scripted word.
"""
import json


def reply(text):
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text},
                                     "finish_reason": "stop"}]}).encode()


def is_sentence_lens(body):
    system = body["messages"][0]["content"]
    return "PLAN or STATE" in system or "TASK or NEW" in system


class Judge:
    def __init__(self, whole_lens_words, sentence_words=("STATE", "TASK")):
        self.whole = list(whole_lens_words)
        self.sentence = dict(zip(("PLAN or STATE", "TASK or NEW"), sentence_words))
        self.bodies = []

    def __call__(self, body, rlog=None):
        self.bodies.append(body)
        system = body["messages"][0]["content"]
        for marker, word in self.sentence.items():
            if marker in system:
                return reply(word)
        return reply(self.whole.pop(0))

    @property
    def whole_bodies(self):
        return [b for b in self.bodies if not is_sentence_lens(b)]
