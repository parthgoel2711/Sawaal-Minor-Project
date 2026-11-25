from app.config import Settings
from app.demo import DemoGenerator, demo_questions
from app.llm import make_generator


def test_demo_provider_selected():
    s = Settings(demo_mode=True)
    assert s.provider == "demo" and s.llm_enabled
    assert isinstance(make_generator(s), DemoGenerator)


def test_demo_questions_exist():
    assert len(demo_questions("ecommerce")) >= 5


def test_demo_generates_gold_sql():
    g = DemoGenerator()
    q = demo_questions("ecommerce")[0]
    schema = "CREATE TABLE customers (id INT);\nCREATE TABLE orders (id INT);\nCREATE TABLE products (id INT);\nCREATE TABLE order_items (id INT);"
    out = g.generate(dialect="sqlite", schema=schema, question=q, history=[], failures=[])
    assert out.answerable and out.sql


def test_demo_refuses_unknown():
    g = DemoGenerator()
    out = g.generate(dialect="sqlite", schema="CREATE TABLE a (x INT)", question="zzz qqq www", history=[], failures=[])
    assert not out.answerable
