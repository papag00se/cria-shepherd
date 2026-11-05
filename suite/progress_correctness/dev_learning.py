"""One preassigned DEV family: language-learning sessions."""
import sys

GROUPS = []
FAMILY = 'dev-language-learning-session'


def add(name, requirement, seed, done, partial, ns, checks, rationale):
    GROUPS.append({'split':'dev','family':FAMILY,'group':FAMILY+'/'+name,'language':'Python',
                   'requirement':requirement, 'seed_files':seed,
                   'snapshots':{'DONE':done,'PARTIAL':partial,'NOT_STARTED':ns},
                   'checks':[{'name':n,'argv':[sys.executable,'-c',c],'files':{},'timeout_seconds':20} for n,c in checks],
                   'rationale':rationale})

seed = '''def advance(card, correct, today):
    return dict(card)
'''
done = '''def advance(card, correct, today):
    updated = dict(card)
    if correct:
        updated['streak'] = card['streak'] + 1
        updated['due'] = today + 2 ** updated['streak']
    else:
        updated['streak'] = 0
        updated['due'] = today + 1
    return updated
'''
partial = '''def advance(card, correct, today):
    updated = dict(card)
    if correct:
        updated['streak'] = card['streak'] + 1
        updated['due'] = today + 2 ** updated['streak']
    else:
        updated['due'] = today + 1
    return updated
'''
ns = '''def advance(card, correct, today):
    result = dict(card)
    return result
'''
add('spaced-review', 'Update learning.py advance(card, correct, today). card is a dictionary with nonnegative integer streak and integer due, plus arbitrary extra fields. Return a new dictionary: for a correct answer increment streak and set due to today + 2**new_streak; for an incorrect answer reset streak to zero and set due to today + 1. Preserve other fields and do not mutate card. today is an integer.',
{'learning.py':seed}, {'learning.py':done}, {'learning.py':partial}, {'learning.py':ns},
[('correct', '''from learning import advance
c={'streak':2,'due':10,'word':'casa'}; assert advance(c,True,11)=={'streak':3,'due':19,'word':'casa'} and c=={'streak':2,'due':10,'word':'casa'}
'''), ('incorrect', '''from learning import advance
c={'streak':3,'due':20,'word':'casa'}; assert advance(c,False,21)=={'streak':0,'due':22,'word':'casa'} and c['streak']==3
''')], 'The partial schedules both outcomes but does not reset the streak after an incorrect answer.')

seed = '''def render(cards):
    return ''
'''
done = '''def render(cards):
    if not cards:
        return 'No cards\\n'
    return ''.join(f"{index}. {card['front']}\\n" for index, card in enumerate(cards, 1))
'''
partial = '''def render(cards):
    return ''.join(f"{index}. {card['front']}\\n" for index, card in enumerate(cards, 1))
'''
ns = '''def render(cards):
    empty_message = ''
    return empty_message
'''
add('session-prompt', 'Update prompt.py render(cards). cards is an ordered list of dictionaries with front strings containing no newlines. For a nonempty list return each front prefixed by its one-based number and a period plus a space, one per line, with a final newline. If there are no cards return exactly "No cards" followed by a newline. Do not modify the list or dictionaries.',
{'prompt.py':seed}, {'prompt.py':done}, {'prompt.py':partial}, {'prompt.py':ns},
[('cards', '''from prompt import render
c=[{'front':'hola'},{'front':'adios'}]; assert render(c)=='1. hola\\n2. adios\\n' and c[0]['front']=='hola'
'''), ('empty', '''from prompt import render
assert render([])=='No cards\\n'
''')], 'The partial formats populated sessions but returns an empty string rather than the required empty-session message.')
