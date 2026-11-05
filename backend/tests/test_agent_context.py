import asyncio

from app.agent import graph

DATASETS = [
    {"name": "bills_2025", "table": "ds.t_bills_2025_f8e28e"},
    {"name": "quotes", "table": "ds.t_quotes_a1b2c3"},
]


def test_used_datasets_matches_physical_table():
    sql = 'SELECT "供应商" FROM ds.t_bills_2025_f8e28e'
    assert graph._used_datasets(sql, DATASETS) == ["bills_2025"]


def test_used_datasets_ignores_table_name_prefix_collision():
    datasets = [
        {"name": "bills", "table": "ds.t_bills_2025"},
        {"name": "bills_extra", "table": "ds.t_bills_2025_x"},
    ]
    assert graph._used_datasets("SELECT * FROM ds.t_bills_2025_x", datasets) == [
        "bills_extra"
    ]


def test_validate_sql_emits_dataset_context():
    events = []
    state = {
        "sql": 'SELECT * FROM ds.t_bills_2025_f8e28e',
        "datasets": DATASETS,
    }
    config = {"configurable": {"emit": lambda event, data: events.append((event, data))}}

    asyncio.run(graph.validate_sql(state, config))

    assert events[0][0] == "sql"
    assert events[0][1]["datasets"] == ["bills_2025"]
