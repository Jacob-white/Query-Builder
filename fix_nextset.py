import re

with open("query_builder/connectors/introspection.py", "r") as f:
    content = f.read()

content = content.replace("if cursor.nextset() is None:\n                            break", "if cursor.nextset() is None:\n                                break")
content = content.replace("if hasattr(cursor, \"nextset\"):\n                            if cursor.nextset() is None:\n                                break", "if hasattr(cursor, \"nextset\"):\n                            if cursor.nextset() is None:\n                                break")

with open("query_builder/connectors/introspection.py", "w") as f:
    f.write(content)
