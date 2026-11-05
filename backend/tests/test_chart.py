from app.agent.chart import _detect_unit, build_chart


def test_bar_chart_uses_planned_axes_and_unit():
    columns = ["供应商", "采购金额(万元)"]
    rows = [["Anthropic", 14610.15], ["DeepSeek", 4951.61]]

    spec = build_chart(
        {"type": "bar", "x": "供应商", "series": ["采购金额(万元)"], "title": "供应商成本"},
        columns,
        rows,
    )

    assert spec is not None
    assert spec["type"] == "bar"
    assert spec["title"] == "供应商成本"
    assert spec["x"] == ["Anthropic", "DeepSeek"]
    assert spec["series"] == [{"name": "采购金额(万元)", "data": [14610.15, 4951.61]}]
    assert spec["unit"] == "万元"


def test_pie_chart_builds_data_pairs():
    columns = ["应用", "成本"]
    rows = [["智能客服", 11673.3], ["代码助手", 6202.74]]

    spec = build_chart({"type": "pie"}, columns, rows)

    assert spec is not None
    assert spec["type"] == "pie"
    assert spec["data"] == [
        {"name": "智能客服", "value": 11673.3},
        {"name": "代码助手", "value": 6202.74},
    ]


def test_pie_with_multiple_numeric_columns_falls_back_to_bar():
    columns = ["供应商", "输入token", "输出token"]
    rows = [["DeepSeek", 100, 20], ["OpenAI", 200, 60]]

    spec = build_chart({"type": "pie"}, columns, rows)

    assert spec is not None
    assert spec["type"] == "bar"
    assert len(spec["series"]) == 2


def test_time_axis_defaults_to_line_for_long_series():
    columns = ["月份", "金额"]
    rows = [[f"2025-{month:02d}", month * 100.0] for month in range(1, 13)]

    spec = build_chart(None, columns, rows)

    assert spec is not None
    assert spec["type"] == "line"
    assert len(spec["x"]) == 12


def test_unsupported_type_defaults_to_bar():
    columns = ["供应商", "金额"]
    rows = [["DeepSeek", 10.0]]

    spec = build_chart({"type": "radar"}, columns, rows)

    assert spec is not None
    assert spec["type"] == "bar"


def test_no_numeric_column_returns_none():
    assert build_chart(None, ["供应商", "合同编号"], [["DeepSeek", "HT-001"]]) is None


def test_empty_rows_returns_none():
    assert build_chart(None, ["供应商", "金额"], []) is None


def test_boolean_values_are_not_treated_as_numbers():
    assert build_chart(None, ["供应商", "已续约"], [["DeepSeek", True]]) is None


def test_unit_detection_prefers_explicit_parentheses():
    assert _detect_unit(["金额(万元)", "金额(元)"], ["金额(万元)"]) == "万元"
    assert _detect_unit(["供应商", "采购金额"], ["采购金额"]) == ""


def test_unit_detection_falls_back_to_known_units():
    assert _detect_unit(["供应商", "成本_万元"], ["成本_万元"]) == "万元"
    assert _detect_unit(["供应商", "调用次数"], ["调用次数"]) == "次"
