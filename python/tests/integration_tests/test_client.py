"""LangSmith langchain_client Integration Tests."""

import datetime
import io
import logging
import os
import random
import string
import sys
import time
import uuid
from datetime import timedelta
from typing import Any, Callable, Dict
from unittest import mock
from uuid import uuid4

import pytest
from freezegun import freeze_time
from pydantic import BaseModel
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

from langsmith.client import ID_TYPE, Client
from langsmith.schemas import DataType
from langsmith.utils import (
    LangSmithConnectionError,
    LangSmithError,
    get_env_var,
)

logger = logging.getLogger(__name__)


def wait_for(
    condition: Callable[[], bool], max_sleep_time: int = 120, sleep_time: int = 3
):
    """Wait for a condition to be true."""
    start_time = time.time()
    while time.time() - start_time < max_sleep_time:
        try:
            if condition():
                return
        except Exception:
            time.sleep(sleep_time)
    total_time = time.time() - start_time
    raise ValueError(f"Callable did not return within {total_time}")


@pytest.fixture
def langchain_client() -> Client:
    get_env_var.cache_clear()
    return Client()


def test_datasets(langchain_client: Client) -> None:
    """Test datasets."""
    csv_content = "col1,col2\nval1,val2"
    blob_data = io.BytesIO(csv_content.encode("utf-8"))

    description = "Test Dataset"
    input_keys = ["col1"]
    output_keys = ["col2"]
    filename = "".join(random.sample(string.ascii_lowercase, 10)) + ".csv"
    new_dataset = langchain_client.upload_csv(
        csv_file=(filename, blob_data),
        description=description,
        input_keys=input_keys,
        output_keys=output_keys,
    )
    assert new_dataset.id is not None
    assert new_dataset.description == description

    dataset = langchain_client.read_dataset(dataset_id=new_dataset.id)
    dataset_id = dataset.id
    dataset2 = langchain_client.read_dataset(dataset_id=dataset_id)
    assert dataset.id == dataset2.id

    datasets = list(langchain_client.list_datasets())
    assert len(datasets) > 0
    assert dataset_id in [dataset.id for dataset in datasets]

    # Test Example CRD
    example = langchain_client.create_example(
        inputs={"col1": "addedExampleCol1"},
        outputs={"col2": "addedExampleCol2"},
        dataset_id=new_dataset.id,
    )
    example_value = langchain_client.read_example(example.id)
    assert example_value.inputs is not None
    assert example_value.inputs["col1"] == "addedExampleCol1"
    assert example_value.outputs is not None
    assert example_value.outputs["col2"] == "addedExampleCol2"

    examples = list(
        langchain_client.list_examples(dataset_id=new_dataset.id)  # type: ignore
    )
    assert len(examples) == 2
    assert example.id in [example.id for example in examples]

    langchain_client.update_example(
        example_id=example.id,
        inputs={"col1": "updatedExampleCol1"},
        outputs={"col2": "updatedExampleCol2"},
        metadata={"foo": "bar"},
    )
    updated_example = langchain_client.read_example(example.id)
    assert updated_example.id == example.id
    updated_example_value = langchain_client.read_example(updated_example.id)
    assert updated_example_value.inputs["col1"] == "updatedExampleCol1"
    assert updated_example_value.outputs is not None
    assert updated_example_value.outputs["col2"] == "updatedExampleCol2"
    assert (updated_example_value.metadata or {}).get("foo") == "bar"

    new_example = langchain_client.create_example(
        inputs={"col1": "newAddedExampleCol1"},
        outputs={"col2": "newAddedExampleCol2"},
        dataset_id=new_dataset.id,
    )
    example_value = langchain_client.read_example(new_example.id)
    assert example_value.inputs is not None
    assert example_value.inputs["col1"] == "newAddedExampleCol1"
    assert example_value.outputs is not None
    assert example_value.outputs["col2"] == "newAddedExampleCol2"

    langchain_client.update_examples(
        example_ids=[new_example.id, example.id],
        inputs=[{"col1": "newUpdatedExampleCol1"}, {"col1": "newNewUpdatedExampleCol"}],
        outputs=[
            {"col2": "newUpdatedExampleCol2"},
            {"col2": "newNewUpdatedExampleCol2"},
        ],
        metadata=[{"foo": "baz"}, {"foo": "qux"}],
    )
    updated_example = langchain_client.read_example(new_example.id)
    assert updated_example.id == new_example.id
    assert updated_example.inputs["col1"] == "newUpdatedExampleCol1"
    assert updated_example.outputs is not None
    assert updated_example.outputs["col2"] == "newUpdatedExampleCol2"
    assert (updated_example.metadata or {}).get("foo") == "baz"

    updated_example = langchain_client.read_example(example.id)
    assert updated_example.id == example.id
    assert updated_example.inputs["col1"] == "newNewUpdatedExampleCol"
    assert updated_example.outputs is not None
    assert updated_example.outputs["col2"] == "newNewUpdatedExampleCol2"
    assert (updated_example.metadata or {}).get("foo") == "qux"

    langchain_client.delete_example(example.id)
    examples2 = list(
        langchain_client.list_examples(dataset_id=new_dataset.id)  # type: ignore
    )
    assert len(examples2) == 2
    langchain_client.delete_dataset(dataset_id=dataset_id)


def test_list_examples(langchain_client: Client) -> None:
    """Test list_examples."""
    examples = [
        ("Shut up, idiot", "Toxic", ["train", "validation"]),
        ("You're a wonderful person", "Not toxic", "test"),
        ("This is the worst thing ever", "Toxic", ["train"]),
        ("I had a great day today", "Not toxic", "test"),
        ("Nobody likes you", "Toxic", "train"),
        ("This is unacceptable. I want to speak to the manager.", "Not toxic", None),
    ]

    dataset_name = "__test_list_examples" + uuid4().hex[:4]
    dataset = langchain_client.create_dataset(dataset_name=dataset_name)
    inputs, outputs, splits = zip(
        *[({"text": text}, {"label": label}, split) for text, label, split in examples]
    )
    langchain_client.create_examples(
        inputs=inputs, outputs=outputs, splits=splits, dataset_id=dataset.id
    )
    example_list = list(langchain_client.list_examples(dataset_id=dataset.id))
    assert len(example_list) == len(examples)

    example_list = list(
        langchain_client.list_examples(dataset_id=dataset.id, offset=1, limit=2)
    )
    assert len(example_list) == 2

    example_list = list(langchain_client.list_examples(dataset_id=dataset.id, offset=1))
    assert len(example_list) == len(examples) - 1

    example_list = list(
        langchain_client.list_examples(dataset_id=dataset.id, splits=["train"])
    )
    assert len(example_list) == 3

    example_list = list(
        langchain_client.list_examples(dataset_id=dataset.id, splits=["validation"])
    )
    assert len(example_list) == 1

    example_list = list(
        langchain_client.list_examples(dataset_id=dataset.id, splits=["test"])
    )
    assert len(example_list) == 2

    example_list = list(
        langchain_client.list_examples(dataset_id=dataset.id, splits=["train", "test"])
    )
    assert len(example_list) == 5

    langchain_client.update_example(
        example_id=[
            example.id
            for example in example_list
            if example.metadata is not None
            and "test" in example.metadata.get("dataset_split", [])
        ][0],
        split="train",
    )

    example_list = list(
        langchain_client.list_examples(dataset_id=dataset.id, splits=["test"])
    )
    assert len(example_list) == 1

    example_list = list(
        langchain_client.list_examples(dataset_id=dataset.id, splits=["train"])
    )
    assert len(example_list) == 4

    langchain_client.create_example(
        inputs={"text": "What's up!"},
        outputs={"label": "Not toxic"},
        metadata={"foo": "bar", "baz": "qux"},
        dataset_name=dataset_name,
    )

    example_list = list(langchain_client.list_examples(dataset_id=dataset.id))
    assert len(example_list) == len(examples) + 1

    example_list = list(
        langchain_client.list_examples(dataset_id=dataset.id, metadata={"foo": "bar"})
    )
    assert len(example_list) == 1

    example_list = list(
        langchain_client.list_examples(dataset_id=dataset.id, metadata={"baz": "qux"})
    )
    assert len(example_list) == 1

    example_list = list(
        langchain_client.list_examples(
            dataset_id=dataset.id, metadata={"foo": "bar", "baz": "qux"}
        )
    )
    assert len(example_list) == 1

    example_list = list(
        langchain_client.list_examples(
            dataset_id=dataset.id, metadata={"foo": "bar", "baz": "quux"}
        )
    )
    assert len(example_list) == 0

    example_list = list(
        langchain_client.list_examples(
            dataset_id=dataset.id, filter='exists(metadata, "baz")'
        )
    )
    assert len(example_list) == 1

    example_list = list(
        langchain_client.list_examples(
            dataset_id=dataset.id, filter='has("metadata", \'{"foo": "bar"}\')'
        )
    )
    assert len(example_list) == 1

    example_list = list(
        langchain_client.list_examples(
            dataset_id=dataset.id, filter='exists(metadata, "bazzz")'
        )
    )
    assert len(example_list) == 0

    langchain_client.delete_dataset(dataset_id=dataset.id)


@pytest.mark.slow
def test_similar_examples(langchain_client: Client) -> None:
    inputs = [{"text": "how are you"}, {"text": "good bye"}, {"text": "see ya later"}]
    outputs = [
        {"response": "good how are you"},
        {"response": "ta ta"},
        {"response": "tootles"},
    ]
    dataset_name = "__test_similar_examples" + uuid4().hex[:4]
    dataset = langchain_client.create_dataset(
        dataset_name=dataset_name,
        inputs_schema={
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        outputs_schema={
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "response": {"type": "string"},
            },
            "required": ["response"],
            "additionalProperties": False,
        },
    )
    langchain_client.create_examples(
        inputs=inputs, outputs=outputs, dataset_id=dataset.id
    )
    langchain_client.index_dataset(dataset_id=dataset.id)
    # Need to wait for indexing to finish.
    time.sleep(5)
    similar_list = langchain_client.similar_examples(
        {"text": "howdy"}, limit=2, dataset_id=dataset.id
    )
    assert len(similar_list) == 2

    langchain_client.delete_dataset(dataset_id=dataset.id)


@pytest.mark.skip(reason="This test is flaky")
def test_persist_update_run(langchain_client: Client) -> None:
    """Test the persist and update methods work as expected."""
    project_name = "__test_persist_update_run" + uuid4().hex[:4]
    if langchain_client.has_project(project_name):
        langchain_client.delete_project(project_name=project_name)
    try:
        start_time = datetime.datetime.now()
        revision_id = uuid4()
        run: dict = dict(
            id=uuid4(),
            name="test_run",
            run_type="llm",
            inputs={"text": "hello world"},
            project_name=project_name,
            api_url=os.getenv("LANGCHAIN_ENDPOINT"),
            start_time=start_time,
            extra={"extra": "extra"},
            revision_id=revision_id,
        )
        langchain_client.create_run(**run)
        run["outputs"] = {"output": ["Hi"]}
        run["extra"]["foo"] = "bar"
        run["name"] = "test_run_updated"
        langchain_client.update_run(run["id"], **run)
        wait_for(lambda: langchain_client.read_run(run["id"]).end_time is not None)
        stored_run = langchain_client.read_run(run["id"])
        assert stored_run.name == run["name"]
        assert stored_run.id == run["id"]
        assert stored_run.outputs == run["outputs"]
        assert stored_run.start_time == run["start_time"]
        assert stored_run.revision_id == str(revision_id)
    finally:
        langchain_client.delete_project(project_name=project_name)


@pytest.mark.parametrize("uri", ["http://localhost:1981", "http://api.langchain.minus"])
def test_error_surfaced_invalid_uri(uri: str) -> None:
    get_env_var.cache_clear()
    client = Client(api_url=uri, api_key="test")
    # expect connect error
    with pytest.raises(LangSmithConnectionError):
        client.create_run("My Run", inputs={"text": "hello world"}, run_type="llm")


def test_create_dataset(langchain_client: Client) -> None:
    dataset_name = "__test_create_dataset" + uuid4().hex[:4]
    if langchain_client.has_dataset(dataset_name=dataset_name):
        langchain_client.delete_dataset(dataset_name=dataset_name)
    dataset = langchain_client.create_dataset(dataset_name, data_type=DataType.llm)
    ground_truth = "bcde"
    example = langchain_client.create_example(
        inputs={"input": "hello world"},
        outputs={"output": ground_truth},
        dataset_id=dataset.id,
    )
    initial_version = example.modified_at
    loaded_dataset = langchain_client.read_dataset(dataset_name=dataset_name)
    assert loaded_dataset.data_type == DataType.llm
    example_2 = langchain_client.create_example(
        inputs={"input": "hello world 2"},
        outputs={"output": "fghi"},
        dataset_id=dataset.id,
    )
    langchain_client.update_example(
        example_id=example.id,
        inputs={"input": "hello world"},
        outputs={"output": "bcde"},
    )
    initial_examples = list(
        langchain_client.list_examples(dataset_id=dataset.id, as_of=initial_version)
    )
    assert len(initial_examples) == 1
    latest_examples = list(langchain_client.list_examples(dataset_id=dataset.id))
    assert len(latest_examples) == 2
    latest_tagged_examples = list(
        langchain_client.list_examples(dataset_id=dataset.id, as_of="latest")
    )
    assert len(latest_tagged_examples) == 2
    assert latest_tagged_examples == latest_examples
    diffs = langchain_client.diff_dataset_versions(
        loaded_dataset.id, from_version=initial_version, to_version="latest"
    )
    assert diffs.examples_added == [example_2.id]
    assert diffs.examples_removed == []
    assert diffs.examples_modified == [example.id]
    langchain_client.delete_dataset(dataset_id=dataset.id)


def test_dataset_schema_validation(langchain_client: Client) -> None:
    dataset_name = "__test_create_dataset" + uuid4().hex[:4]
    if langchain_client.has_dataset(dataset_name=dataset_name):
        langchain_client.delete_dataset(dataset_name=dataset_name)

    class InputSchema(BaseModel):
        input: str

    class OutputSchema(BaseModel):
        output: str

    dataset = langchain_client.create_dataset(
        dataset_name,
        data_type=DataType.kv,
        inputs_schema=InputSchema.model_json_schema(),
        outputs_schema=OutputSchema.model_json_schema(),
    )

    # confirm we store the schema from the create request
    assert dataset.inputs_schema == InputSchema.model_json_schema()
    assert dataset.outputs_schema == OutputSchema.model_json_schema()

    # create an example that matches the schema, which should succeed
    langchain_client.create_example(
        inputs={"input": "hello world"},
        outputs={"output": "hello"},
        dataset_id=dataset.id,
    )

    # create an example that does not match the input schema
    with pytest.raises(LangSmithError):
        langchain_client.create_example(
            inputs={"john": 1},
            outputs={"output": "hello"},
            dataset_id=dataset.id,
        )

    # create an example that does not match the output schema
    with pytest.raises(LangSmithError):
        langchain_client.create_example(
            inputs={"input": "hello world"},
            outputs={"john": 1},
            dataset_id=dataset.id,
        )

    # assert read API includes the schema definition
    read_dataset = langchain_client.read_dataset(dataset_id=dataset.id)
    assert read_dataset.inputs_schema == InputSchema.model_json_schema()
    assert read_dataset.outputs_schema == OutputSchema.model_json_schema()

    langchain_client.delete_dataset(dataset_id=dataset.id)


@freeze_time("2023-01-01")
def test_list_datasets(langchain_client: Client) -> None:
    ds1n = "__test_list_datasets1" + uuid4().hex[:4]
    ds2n = "__test_list_datasets2" + uuid4().hex[:4]
    try:
        dataset1 = langchain_client.create_dataset(
            ds1n, data_type=DataType.llm, metadata={"foo": "barqux"}
        )
        dataset2 = langchain_client.create_dataset(ds2n, data_type=DataType.kv)
        assert dataset1.url is not None
        assert dataset2.url is not None
        datasets = list(
            langchain_client.list_datasets(dataset_ids=[dataset1.id, dataset2.id])
        )
        assert len(datasets) == 2
        assert dataset1.id in [dataset.id for dataset in datasets]
        assert dataset2.id in [dataset.id for dataset in datasets]
        assert dataset1.data_type == DataType.llm
        assert dataset2.data_type == DataType.kv
        # Sub-filter on data type
        datasets = list(langchain_client.list_datasets(data_type=DataType.llm.value))
        assert len(datasets) > 0
        assert dataset1.id in {dataset.id for dataset in datasets}
        # Sub-filter on name
        datasets = list(
            langchain_client.list_datasets(
                dataset_ids=[dataset1.id, dataset2.id], dataset_name=ds1n
            )
        )
        assert len(datasets) == 1
        # Sub-filter on metadata
        datasets = list(
            langchain_client.list_datasets(
                dataset_ids=[dataset1.id, dataset2.id], metadata={"foo": "barqux"}
            )
        )
        assert len(datasets) == 1
    finally:
        # Delete datasets
        for name in [ds1n, ds2n]:
            try:
                langchain_client.delete_dataset(dataset_name=name)
            except LangSmithError:
                pass


@pytest.mark.skip(reason="This test is flaky")
def test_create_run_with_masked_inputs_outputs(
    langchain_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_name = "__test_create_run_with_masked_inputs_outputs" + uuid4().hex[:4]
    monkeypatch.setenv("LANGCHAIN_HIDE_INPUTS", "true")
    monkeypatch.setenv("LANGCHAIN_HIDE_OUTPUTS", "true")
    if langchain_client.has_project(project_name):
        langchain_client.delete_project(project_name=project_name)
    try:
        run_id = uuid4()
        langchain_client.create_run(
            id=run_id,
            project_name=project_name,
            name="test_run",
            run_type="llm",
            inputs={"prompt": "hello world"},
            outputs={"generation": "hi there"},
            start_time=datetime.datetime.now(datetime.timezone.utc),
            end_time=datetime.datetime.now(datetime.timezone.utc),
            hide_inputs=True,
            hide_outputs=True,
        )

        run_id2 = uuid4()
        langchain_client.create_run(
            id=run_id2,
            project_name=project_name,
            name="test_run_2",
            run_type="llm",
            inputs={"messages": "hello world 2"},
            start_time=datetime.datetime.now(datetime.timezone.utc),
            hide_inputs=True,
        )

        langchain_client.update_run(
            run_id2,
            outputs={"generation": "hi there 2"},
            end_time=datetime.datetime.now(datetime.timezone.utc),
            hide_outputs=True,
        )
        wait_for(lambda: langchain_client.read_run(run_id).end_time is not None)
        stored_run = langchain_client.read_run(run_id)
        assert "hello" not in str(stored_run.inputs)
        assert stored_run.outputs is not None
        assert "hi" not in str(stored_run.outputs)
        wait_for(lambda: langchain_client.read_run(run_id2).end_time is not None)
        stored_run2 = langchain_client.read_run(run_id2)
        assert "hello" not in str(stored_run2.inputs)
        assert stored_run2.outputs is not None
        assert "hi" not in str(stored_run2.outputs)
    finally:
        langchain_client.delete_project(project_name=project_name)


@freeze_time("2023-01-01")
def test_create_chat_example(
    monkeypatch: pytest.MonkeyPatch, langchain_client: Client
) -> None:
    from langchain.schema import FunctionMessage, HumanMessage

    dataset_name = "__createChatExample-test-dataset"
    try:
        existing_dataset = langchain_client.read_dataset(dataset_name=dataset_name)
        langchain_client.delete_dataset(dataset_id=existing_dataset.id)
    except LangSmithError:
        # If the dataset doesn't exist,
        pass

    dataset = langchain_client.create_dataset(dataset_name)

    input = [HumanMessage(content="Hello, world!")]
    generation = FunctionMessage(
        name="foo",
        content="",
        additional_kwargs={"function_call": {"arguments": "args", "name": "foo"}},
    )
    # Create the example from messages
    langchain_client.create_chat_example(input, generation, dataset_id=dataset.id)

    # Read the example
    examples = []
    for example in langchain_client.list_examples(dataset_id=dataset.id):
        examples.append(example)
    assert len(examples) == 1
    assert examples[0].inputs == {
        "input": [
            {
                "type": "human",
                "data": {"content": "Hello, world!"},
            },
        ],
    }
    assert examples[0].outputs == {
        "output": {
            "type": "function",
            "data": {
                "content": "",
                "additional_kwargs": {
                    "function_call": {"arguments": "args", "name": "foo"}
                },
            },
        },
    }
    langchain_client.delete_dataset(dataset_id=dataset.id)


@pytest.mark.parametrize("use_multipart_endpoint", [True, False])
def test_batch_ingest_runs(
    langchain_client: Client, use_multipart_endpoint: bool
) -> None:
    _session = "__test_batch_ingest_runs"
    trace_id = uuid4()
    trace_id_2 = uuid4()
    run_id_2 = uuid4()
    current_time = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    later_time = (
        datetime.datetime.now(datetime.timezone.utc) + timedelta(seconds=1)
    ).strftime("%Y%m%dT%H%M%S%fZ")

    """
    Here we create:
    - run 1: a top level trace with inputs and outputs
    - run 3: a top level trace with an error with inputs and outputs
    - run 2: a child of run 1 with inputs, no outputs
    and we update:
    - run 2 (the child): to add outputs
    """

    runs_to_create = [
        {
            "id": str(trace_id),
            "session_name": _session,
            "name": "run 1",
            "run_type": "chain",
            "dotted_order": f"{current_time}{str(trace_id)}",
            "trace_id": str(trace_id),
            "inputs": {"input1": 1, "input2": 2},
            "outputs": {"output1": 3, "output2": 4},
        },
        {
            "id": str(trace_id_2),
            "session_name": _session,
            "name": "run 3",
            "run_type": "chain",
            "dotted_order": f"{current_time}{str(trace_id_2)}",
            "trace_id": str(trace_id_2),
            "inputs": {"input1": 1, "input2": 2},
            "error": "error",
        },
        {
            "id": str(run_id_2),
            "session_name": _session,
            "name": "run 2",
            "run_type": "chain",
            "dotted_order": f"{current_time}{str(trace_id)}."
            f"{later_time}{str(run_id_2)}",
            "trace_id": str(trace_id),
            "parent_run_id": str(trace_id),
            "inputs": {"input1": 5, "input2": 6},
        },
    ]
    runs_to_update = [
        {
            "id": str(run_id_2),
            "dotted_order": f"{current_time}{str(trace_id)}."
            f"{later_time}{str(run_id_2)}",
            "trace_id": str(trace_id),
            "parent_run_id": str(trace_id),
            "outputs": {"output1": 4, "output2": 5},
        },
    ]
    if use_multipart_endpoint:
        langchain_client.multipart_ingest(create=runs_to_create, update=runs_to_update)
    else:
        langchain_client.batch_ingest_runs(create=runs_to_create, update=runs_to_update)
    runs = []
    wait = 4
    for _ in range(15):
        try:
            runs = list(
                langchain_client.list_runs(
                    project_name=_session,
                    run_ids=[str(trace_id), str(run_id_2), str(trace_id_2)],
                )
            )
            if len(runs) == 3:
                break
            raise LangSmithError("Runs not created yet")
        except LangSmithError:
            time.sleep(wait)
            wait += 1
    else:
        raise ValueError("Runs not created in time")
    assert len(runs) == 3
    # Write all the assertions here
    assert len(runs) == 3

    # Assert inputs and outputs of run 1
    run1 = next(run for run in runs if run.id == trace_id)
    assert run1.inputs == {"input1": 1, "input2": 2}
    assert run1.outputs == {"output1": 3, "output2": 4}

    # Assert inputs and outputs of run 2
    run2 = next(run for run in runs if run.id == run_id_2)
    assert run2.inputs == {"input1": 5, "input2": 6}
    assert run2.outputs == {"output1": 4, "output2": 5}

    # Assert inputs and outputs of run 3
    run3 = next(run for run in runs if run.id == trace_id_2)
    assert run3.inputs == {"input1": 1, "input2": 2}
    assert run3.error == "error"


def test_multipart_ingest_empty(
    langchain_client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    runs_to_create: list[dict] = []
    runs_to_update: list[dict] = []

    # make sure no warnings logged
    with caplog.at_level(logging.WARNING, logger="langsmith.client"):
        langchain_client.multipart_ingest(create=runs_to_create, update=runs_to_update)

        assert not caplog.records


def test_multipart_ingest_create_then_update(
    langchain_client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    _session = "__test_multipart_ingest_create_then_update"

    trace_a_id = uuid4()
    current_time = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )

    runs_to_create: list[dict] = [
        {
            "id": str(trace_a_id),
            "session_name": _session,
            "name": "trace a root",
            "run_type": "chain",
            "dotted_order": f"{current_time}{str(trace_a_id)}",
            "trace_id": str(trace_a_id),
            "inputs": {"input1": 1, "input2": 2},
        }
    ]

    # make sure no warnings logged
    with caplog.at_level(logging.WARNING, logger="langsmith.client"):
        langchain_client.multipart_ingest(create=runs_to_create, update=[])

        assert not caplog.records

    runs_to_update: list[dict] = [
        {
            "id": str(trace_a_id),
            "dotted_order": f"{current_time}{str(trace_a_id)}",
            "trace_id": str(trace_a_id),
            "outputs": {"output1": 3, "output2": 4},
        }
    ]
    with caplog.at_level(logging.WARNING, logger="langsmith.client"):
        langchain_client.multipart_ingest(create=[], update=runs_to_update)

        assert not caplog.records


def test_multipart_ingest_update_then_create(
    langchain_client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    _session = "__test_multipart_ingest_update_then_create"

    trace_a_id = uuid4()
    current_time = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )

    runs_to_update: list[dict] = [
        {
            "id": str(trace_a_id),
            "dotted_order": f"{current_time}{str(trace_a_id)}",
            "trace_id": str(trace_a_id),
            "outputs": {"output1": 3, "output2": 4},
        }
    ]

    # make sure no warnings logged
    with caplog.at_level(logging.WARNING, logger="langsmith.client"):
        langchain_client.multipart_ingest(create=[], update=runs_to_update)

        assert not caplog.records

    runs_to_create: list[dict] = [
        {
            "id": str(trace_a_id),
            "session_name": _session,
            "name": "trace a root",
            "run_type": "chain",
            "dotted_order": f"{current_time}{str(trace_a_id)}",
            "trace_id": str(trace_a_id),
            "inputs": {"input1": 1, "input2": 2},
        }
    ]

    with caplog.at_level(logging.WARNING, logger="langsmith.client"):
        langchain_client.multipart_ingest(create=runs_to_create, update=[])

        assert not caplog.records


def test_multipart_ingest_create_wrong_type(
    langchain_client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    _session = "__test_multipart_ingest_create_then_update"

    trace_a_id = uuid4()
    current_time = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )

    runs_to_create: list[dict] = [
        {
            "id": str(trace_a_id),
            "session_name": _session,
            "name": "trace a root",
            "run_type": "agent",
            "dotted_order": f"{current_time}{str(trace_a_id)}",
            "trace_id": str(trace_a_id),
            "inputs": {"input1": 1, "input2": 2},
        }
    ]

    # make sure no warnings logged
    with caplog.at_level(logging.WARNING, logger="langsmith.client"):
        langchain_client.multipart_ingest(create=runs_to_create, update=[])

        # this should 422
        assert len(caplog.records) == 1, "Should get 1 warning for 422, not retried"
        assert all("422" in record.message for record in caplog.records)


@freeze_time("2023-01-01")
def test_get_info() -> None:
    langchain_client = Client(api_key="not-a-real-key")
    info = langchain_client.info
    assert info
    assert info.version is not None  # type: ignore
    assert info.batch_ingest_config is not None  # type: ignore
    assert info.batch_ingest_config["size_limit"] > 0  # type: ignore


@pytest.mark.skip(reason="This test is flaky")
@pytest.mark.parametrize("add_metadata", [True, False])
@pytest.mark.parametrize("do_batching", [True, False])
def test_update_run_extra(add_metadata: bool, do_batching: bool) -> None:
    langchain_client = Client()
    run_id = uuid4()
    run: Dict[str, Any] = {
        "id": run_id,
        "name": "run 1",
        "start_time": datetime.datetime.now(datetime.timezone.utc),
        "run_type": "chain",
        "inputs": {"input1": 1, "input2": 2},
        "outputs": {"output1": 3, "output2": 4},
        "extra": {
            "metadata": {
                "foo": "bar",
            }
        },
        "tags": ["tag1", "tag2"],
    }
    if do_batching:
        run["trace_id"] = run_id
        dotted_order = run["start_time"].strftime("%Y%m%dT%H%M%S%fZ") + str(run_id)  # type: ignore
        run["dotted_order"] = dotted_order
    revision_id = uuid4()
    langchain_client.create_run(**run, revision_id=revision_id)  # type: ignore

    def _get_run(run_id: ID_TYPE, has_end: bool = False) -> bool:
        try:
            r = langchain_client.read_run(run_id)  # type: ignore
            if has_end:
                return r.end_time is not None
            return True
        except LangSmithError:
            return False

    wait_for(lambda: _get_run(run_id))
    created_run = langchain_client.read_run(run_id)
    assert created_run.metadata["foo"] == "bar"
    assert created_run.metadata["revision_id"] == str(revision_id)
    # Update the run
    if add_metadata:
        run["extra"]["metadata"]["foo2"] = "baz"  # type: ignore
        run["tags"] = ["tag3"]
    langchain_client.update_run(run_id, **run)  # type: ignore
    wait_for(lambda: _get_run(run_id, has_end=True))
    updated_run = langchain_client.read_run(run_id)
    assert updated_run.metadata["foo"] == "bar"  # type: ignore
    assert updated_run.revision_id == str(revision_id)
    if add_metadata:
        updated_run.metadata["foo2"] == "baz"  # type: ignore
        assert updated_run.tags == ["tag3"]
    else:
        assert updated_run.tags == ["tag1", "tag2"]
    assert updated_run.extra["runtime"] == created_run.extra["runtime"]  # type: ignore


def test_surrogates():
    chars = "".join(chr(cp) for cp in range(0, sys.maxunicode + 1))
    trans_table = str.maketrans("", "", "")
    all_chars = chars.translate(trans_table)
    langchain_client = Client()
    langchain_client.create_run(
        name="test_run",
        inputs={
            "text": [
                "Hello\ud83d\ude00",
                "Python\ud83d\udc0d",
                "Surrogate\ud834\udd1e",
                "Example\ud83c\udf89",
                "String\ud83c\udfa7",
                "With\ud83c\udf08",
                "Surrogates\ud83d\ude0e",
                "Embedded\ud83d\udcbb",
                "In\ud83c\udf0e",
                "The\ud83d\udcd6",
                "Text\ud83d\udcac",
                "收花🙄·到",
            ]
        },
        run_type="llm",
        end_time=datetime.datetime.now(datetime.timezone.utc),
    )
    langchain_client.create_run(
        name="test_run",
        inputs={
            "text": all_chars,
        },
        run_type="llm",
        end_time=datetime.datetime.now(datetime.timezone.utc),
    )


def test_runs_stats():
    langchain_client = Client()
    # We always have stuff in the "default" project...
    stats = langchain_client.get_run_stats(project_names=["default"], run_type="llm")
    assert stats


def test_slow_run_read_multipart(
    langchain_client: Client, caplog: pytest.LogCaptureFixture
):
    myobj = {f"key_{i}": f"val_{i}" for i in range(500)}
    id_ = str(uuid.uuid4())
    current_time = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    run_to_create = {
        "id": id_,
        "session_name": "default",
        "name": "trace a root",
        "run_type": "chain",
        "dotted_order": f"{current_time}{id_}",
        "trace_id": id_,
        "inputs": myobj,
    }

    class CB:
        def __init__(self):
            self.called = 0
            self.start_time = None

        def __call__(self, monitor: MultipartEncoderMonitor):
            self.called += 1
            if not self.start_time:
                self.start_time = time.time()
            logger.debug(
                f"[{self.called}]: {monitor.bytes_read} bytes,"
                f" {time.time() - self.start_time:.2f} seconds"
                " elapsed",
            )
            if self.called == 1:
                time.sleep(6)

    def create_encoder(*args, **kwargs):
        encoder = MultipartEncoder(*args, **kwargs)
        encoder = MultipartEncoderMonitor(encoder, CB())
        return encoder

    with caplog.at_level(logging.WARNING, logger="langsmith.client"):
        with mock.patch(
            "langsmith.client.rqtb_multipart.MultipartEncoder", create_encoder
        ):
            langchain_client.create_run(**run_to_create)
            time.sleep(1)
            start_time = time.time()
            while time.time() - start_time < 8:
                myobj["key_1"]

        assert not caplog.records
