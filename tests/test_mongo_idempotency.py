from types import SimpleNamespace
from unittest.mock import Mock

from pymongo.errors import DuplicateKeyError

from autoe2e import infer_utils


def test_functionality_text_normalization_is_stable() -> None:
    assert infer_utils._normalized_functionality_text(
        "  ADD   product to Cart "
    ) == infer_utils._normalized_functionality_text("add product to cart")
    assert infer_utils._stable_key("same") == infer_utils._stable_key("same")
    assert infer_utils._stable_key("same") != infer_utils._stable_key("different")


def test_no_match_insert_reuses_concurrently_inserted_functionality(monkeypatch) -> None:
    collection = Mock()
    collection.update_one.side_effect = DuplicateKeyError("duplicate key")
    collection.find_one.return_value = {"_id": "existing"}
    monkeypatch.setattr(infer_utils, "func_db", collection)
    monkeypatch.setenv("APP_NAME", "test-app")
    monkeypatch.setattr(infer_utils, "geometric_score", lambda rank: 0.5)

    result = infer_utils.no_match_insert({
        "text": "Add product to cart",
        "embedding": [0.1, 0.2],
        "rank": 0,
    })

    assert result == "existing"
    query = collection.update_one.call_args.args[0]
    assert query["app"] == "test-app"
    assert query["text_key"] == infer_utils._stable_key(
        infer_utils._normalized_functionality_text("Add product to cart")
    )
    assert collection.update_one.call_args.kwargs["upsert"] is True


def test_action_functionality_relation_uses_idempotent_upsert(monkeypatch) -> None:
    collection = Mock()
    monkeypatch.setattr(infer_utils, "action_func_db", collection)
    monkeypatch.setenv("APP_NAME", "test-app")
    monkeypatch.setattr(infer_utils, "geometric_score", lambda rank: 0.5)

    infer_utils.insert_action_functionality(
        func_ids=["function-1"],
        state_id="state-1",
        state_url="https://example.test",
        prev_state_id=None,
        action_id="action-1",
        prev_action_id=None,
        action_test_id="button-1",
        action_depth=0,
    )

    query, update = collection.update_one.call_args.args[:2]
    assert query["app"] == "test-app"
    assert query["dedupe_key"] == update["$setOnInsert"]["dedupe_key"]
    assert update["$setOnInsert"]["func_pointer"] == "function-1"
    assert collection.update_one.call_args.kwargs["upsert"] is True


def test_match_update_reuses_existing_normalized_functionality(monkeypatch) -> None:
    function_collection = Mock()
    function_collection.find_one.return_value = {"_id": "canonical"}
    action_collection = Mock()
    monkeypatch.setattr(infer_utils, "func_db", function_collection)
    monkeypatch.setattr(infer_utils, "action_func_db", action_collection)
    monkeypatch.setattr(
        infer_utils,
        "openai_embeddings",
        SimpleNamespace(embed_query=lambda text: [0.3, 0.4]),
    )
    monkeypatch.setenv("APP_NAME", "test-app")

    result = infer_utils.match_update({
        "match_id": ["duplicate", "canonical"],
        "combined_text": "Add product to cart",
    })

    assert result == "canonical"
    action_collection.update_many.assert_called_once()
    assert action_collection.update_many.call_args.kwargs["filter"]["func_pointer"] == {
        "$in": ["duplicate"]
    }
    function_collection.delete_many.assert_called_once()
