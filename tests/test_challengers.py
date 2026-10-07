"""What: checks the challenger comparison runs end to end and includes every model and blend.
Why:  the comparison is evidence for decisions; it must not silently drop a model."""
from ctrp.models import challengers as C


def test_compare_runs_every_model_and_blend(extracts):
    table, detail, weights = C.compare(extracts, test_from=2, boot=False)
    expected = set(C.CHALLENGERS) | set(C.BLENDS) | {C.STACKED}
    assert expected <= set(table.index)
    assert detail['lift_top5'].notna().all()
    assert abs(weights['expert weight'].sum() - 1) < 1e-9
