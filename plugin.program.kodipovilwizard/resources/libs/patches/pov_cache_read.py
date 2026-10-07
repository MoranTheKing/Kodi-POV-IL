"""Read caches written by both POV's repr and JSON serializers."""
import ast
import json


def loads(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        # This parses data literals only. Never evaluate source or discard
        # favourites/watched data to migrate an encoding.
        return ast.literal_eval(raw)
