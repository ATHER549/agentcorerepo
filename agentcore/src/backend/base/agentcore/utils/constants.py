from typing import Any


DEFAULT_PYTHON_FUNCTION = """
def python_function(text: str) -> str:
    \"\"\"This is a default python function that returns the input text\"\"\"
    return text
"""


PYTHON_BASIC_TYPES = [str, bool, int, float, tuple, list, dict, set]
DIRECT_TYPES = [
    "str",
    "bool",
    "dict",
    "int",
    "float",
    "Any",
    "prompt",
    "code",
    "NestedDict",
    "table",
    "slider",
    "tab",
    "sortableList",
    "auth",
    "connect",
    "query",
    "tools",
    "mcp",
]


LOADERS_INFO: list[dict[str, Any]] = [
    {
        "loader": "AirbyteJSONLoader",
        "name": "Airbyte JSON (.jsonl)",
        "import": "langchain_community.document_loaders.AirbyteJSONLoader",
        "defaultFor": ["jsonl"],
        "allowdTypes": ["jsonl"],
    },
    {
        "loader": "JSONLoader",
        "name": "JSON (.json)",
        "import": "langchain_community.document_loaders.JSONLoader",
        "defaultFor": ["json"],
        "allowdTypes": ["json"],
    },
    {
        "loader": "BSHTMLLoader",
        "name": "BeautifulSoup4 HTML (.html, .htm)",
        "import": "langchain_community.document_loaders.BSHTMLLoader",
        "allowdTypes": ["html", "htm"],
    },
    {
        "loader": "CSVLoader",
        "name": "CSV (.csv)",
        "import": "langchain_community.document_loaders.CSVLoader",
        "defaultFor": ["csv"],
        "allowdTypes": ["csv"],
    },
    {
        "loader": "CoNLLULoader",
        "name": "CoNLL-U (.conllu)",
        "import": "langchain_community.document_loaders.CoNLLULoader",
        "defaultFor": ["conllu"],
        "allowdTypes": ["conllu"],
    },
    {
        "loader": "EverNoteLoader",
        "name": "EverNote (.enex)",
        "import": "langchain_community.document_loaders.EverNoteLoader",
        "defaultFor": ["enex"],
        "allowdTypes": ["enex"],
    },
    {
        "loader": "FacebookChatLoader",
        "name": "Facebook Chat (.json)",
        "import": "langchain_community.document_loaders.FacebookChatLoader",
        "allowdTypes": ["json"],
    },
    {
        "loader": "OutlookMessageLoader",
        "name": "Outlook Message (.msg)",
        "import": "langchain_community.document_loaders.OutlookMessageLoader",
        "defaultFor": ["msg"],
        "allowdTypes": ["msg"],
    },
    {
        "loader": "PyPDFLoader",
        "name": "PyPDF (.pdf)",
        "import": "langchain_community.document_loaders.PyPDFLoader",
        "defaultFor": ["pdf"],
        "allowdTypes": ["pdf"],
    },
    {
        "loader": "STRLoader",
        "name": "Subtitle (.str)",
        "import": "langchain_community.document_loaders.STRLoader",
        "defaultFor": ["str"],
        "allowdTypes": ["str"],
    },
    {
        "loader": "TextLoader",
        "name": "Text (.txt)",
        "import": "langchain_community.document_loaders.TextLoader",
        "defaultFor": ["txt"],
        "allowdTypes": ["txt"],
    },
    {
        "loader": "UnstructuredEmailLoader",
        "name": "Unstructured Email (.eml)",
        "import": "langchain_community.document_loaders.UnstructuredEmailLoader",
        "defaultFor": ["eml"],
        "allowdTypes": ["eml"],
    },
    {
        "loader": "UnstructuredHTMLLoader",
        "name": "Unstructured HTML (.html, .htm)",
        "import": "langchain_community.document_loaders.UnstructuredHTMLLoader",
        "defaultFor": ["html", "htm"],
        "allowdTypes": ["html", "htm"],
    },
    {
        "loader": "UnstructuredMarkdownLoader",
        "name": "Unstructured Markdown (.md)",
        "import": "langchain_community.document_loaders.UnstructuredMarkdownLoader",
        "defaultFor": ["md", "mdx"],
        "allowdTypes": ["md", "mdx"],
    },
    {
        "loader": "UnstructuredPowerPointLoader",
        "name": "Unstructured PowerPoint (.pptx)",
        "import": "langchain_community.document_loaders.UnstructuredPowerPointLoader",
        "defaultFor": ["pptx"],
        "allowdTypes": ["pptx"],
    },
    {
        "loader": "UnstructuredWordLoader",
        "name": "Unstructured Word (.docx)",
        "import": "langchain_community.document_loaders.UnstructuredWordLoader",
        "defaultFor": ["docx"],
        "allowdTypes": ["docx"],
    },
]


MESSAGE_SENDER_AI = "Machine"
MESSAGE_SENDER_USER = "User"
MESSAGE_SENDER_NAME_AI = "AI"
MESSAGE_SENDER_NAME_USER = "User"
