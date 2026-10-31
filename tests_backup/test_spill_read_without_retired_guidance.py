from cria import outboundpolicies, webfetch


def test_spill_read_does_not_calculate_retired_size_guidance(monkeypatch):
    def obsolete(*args, **kwargs):
        raise AssertionError('retired spill read guidance was consulted')
    for name in ('format_for_spill_path', 'spill_reading_hint', 'page_not_file_for_spill_path', 'outline_for_spill_path'):
        monkeypatch.setattr(webfetch, name, obsolete)
    assert outboundpolicies._spill_read_command('./tmp/reference/spec.txt')
