"""
We just need a very basic generator that can be used to generate text from a prompt.
"""

from typing import List

from core.generator import Generator
from core.openai_client import OpenAIClient
from core.data_classes import Document
from core.retriever import FAISSRetriever
from core.embedder import Embedder
from core.data_components import (
    ToEmbedderResponse,
    RetrieverOutputToContextStr,
    ToEmbeddings,
)
from core.db import LocalDocumentDB

from core.component import Component

# TODO: make the environment variable loading more robust, and let users specify the .env path
import dotenv


from core.document_splitter import DocumentSplitter
from core.component import Sequential

from core.functional import generate_component_key

dotenv.load_dotenv()


class SimpleICL(Component):
    def __init__(self, task_desc: str):
        super().__init__()
        model_kwargs = {"model": "gpt-3.5-turbo"}
        preset_prompt_kwargs = {"task_desc_str": task_desc}
        self.vectorizer_settings = {
            "batch_size": 100,
            "model_kwargs": {
                "model": "text-embedding-3-small",
                "dimensions": 256,
                "encoding_format": "float",
            },
        }
        self.retriever_settings = {
            "top_k": 2,
        }
        self.text_splitter_settings = {
            "split_by": "word",
            "chunk_size": 400,
            "chunk_overlap": 200,
        }
        self.generator = Generator(
            model_client=OpenAIClient(),
            model_kwargs=model_kwargs,
            preset_prompt_kwargs=preset_prompt_kwargs,
        )
        self.generator.print_prompt()
        text_splitter = DocumentSplitter(
            split_by=self.text_splitter_settings["split_by"],
            split_length=self.text_splitter_settings["chunk_size"],
            split_overlap=self.text_splitter_settings["chunk_overlap"],
        )
        vectorizer = Embedder(
            model_client=OpenAIClient(),
            # batch_size=self.vectorizer_settings["batch_size"],
            model_kwargs=self.vectorizer_settings["model_kwargs"],
            output_processors=ToEmbedderResponse(),
        )
        self.data_transformer = Sequential(
            text_splitter,
            ToEmbeddings(
                vectorizer=vectorizer,
                batch_size=self.vectorizer_settings["batch_size"],
            ),
        )
        self.data_transformer_key = generate_component_key(self.data_transformer)
        self.retriever_icl = FAISSRetriever(
            top_k=self.retriever_settings["top_k"],
            dimensions=self.vectorizer_settings["model_kwargs"]["dimensions"],
            vectorizer=vectorizer,
        )
        self.retriever_output_processors = RetrieverOutputToContextStr(deduplicate=True)
        self.db_icl = LocalDocumentDB()

    def build_index(self, documents: List[Document]):
        self.db_icl.load_documents(documents)
        self.map_key = self.db_icl.map_data()
        print(f"map_key: {self.map_key}")
        self.data_key = self.db_icl.transform_data(self.data_transformer)
        print(f"data_key: {self.data_key}")
        self.transformed_documents = self.db_icl.get_transformed_data(self.data_key)
        self.retriever_icl.build_index_from_documents(self.transformed_documents)

    ### TODO: use retriever to get the few shot
    def get_few_shot_example_str(self, query: str, top_k: int) -> str:
        retrieved_documents = self.retriever_icl(query, top_k)
        # fill in the document
        for i, retriever_output in enumerate(retrieved_documents):
            retrieved_documents[i].documents = [
                self.transformed_documents[doc_index]
                for doc_index in retriever_output.doc_indexes
            ]
        # convert all the documents to context string

        example_str = self.retriever_output_processors(retrieved_documents)
        return example_str

    def call(self, task_desc: str, query: str, top_k: int) -> str:
        example_str = self.get_few_shot_example_str(query, top_k=2)
        return (
            self.generator.call(
                input=query,
                prompt_kwargs={"task_desc": task_desc, "example_str": example_str},
            ),
            example_str,
        )


if __name__ == "__main__":
    task_desc = "Classify the sentiment of the following reviews as either Positive or Negative."

    example1 = Document(
        text="Review: I absolutely loved the friendly staff and the welcoming atmosphere! Sentiment: Positive",
    )
    example2 = Document(
        text="Review: It was an awful experience, the food was bland and overpriced. Sentiment: Negative",
    )
    example3 = Document(
        text="Review: What a fantastic movie! Had a great time and would watch it again! Sentiment: Positive",
    )

    simple_icl = SimpleICL(task_desc)
    print(simple_icl)
    simple_icl.build_index([example1, example2, example3])
    query = (
        "Review: The concert was a lot of fun and the band was energetic and engaging."
    )
    response, example_str = simple_icl.call(task_desc, query, top_k=2)
    print(f"response: {response}")
    print(f"example_str: {example_str}")
