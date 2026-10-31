"""cria.assistfamilies identity resolution: historical family ids resolve to the current merged family; unknown ids are errors, never guesses."""
import pytest
from cria import assistfamilies as af

def test_a_historical_family_id_resolves_to_its_current_family_and_an_unknown_id_is_an_error():
    """F27/F41/F42 were merged into F40 (lineage keeps them); every detail id maps to exactly one current family; nothing resolves by fallback."""
    assert [af.resolve_family(i) for i in ('F27', 'F41', 'F40')] == ['F40'] * 3 and {'F27', 'F40', 'F41'} <= set(af.BY_ID['F40'].lineage)
    assert af.HISTORICAL_DETAIL_TO_FAMILY['A14'] == af.DETAIL_TO_FAMILY['A14'] == 'F03'
    with pytest.raises(ValueError, match='Unknown family identity'): af.resolve_family('F999')
