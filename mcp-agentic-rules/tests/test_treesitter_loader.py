"""
Tests for tree-sitter grammar loading.
======================================
Guards that get_parser resolves grammars exposed behind named functions
(tree_sitter_typescript exposes language_typescript(), not language())
and degrades gracefully when grammars are missing.
"""

import pytest


def _tree_sitter_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        return True
    except ImportError:
        return False


def _ts_grammar_available() -> bool:
    try:
        import tree_sitter_typescript  # noqa: F401
        return True
    except ImportError:
        return False


class TestGetParser:
    def test_unknown_language_returns_none(self):
        from scripts.treesitter_utils import get_parser
        if get_parser("no_such_language_xyz") is not None:
            raise AssertionError("Unknown grammars must return None, not raise")

    @pytest.mark.skipif(not _tree_sitter_available() or not _ts_grammar_available(),
                        reason="tree-sitter typescript grammar not installed")
    def test_typescript_parser_loads_via_named_function(self):
        from scripts.treesitter_utils import get_parser
        parser = get_parser("typescript")
        if parser is None:
            raise AssertionError(
                "typescript grammar is installed but get_parser returned None; "
                "language_typescript() was not resolved")

    @pytest.mark.skipif(not _tree_sitter_available() or not _ts_grammar_available(),
                        reason="tree-sitter typescript grammar not installed")
    def test_typescript_source_parses(self):
        from scripts.treesitter_utils import get_parser, parse_source
        if get_parser("typescript") is None:
            raise AssertionError("typescript parser must load before parsing")
        tree = parse_source(b"export function greet(name: string): string {\n"
                            b"  return 'hi ' + name;\n}\n", "typescript")
        if tree is None:
            raise AssertionError("Parsing valid TypeScript must produce a tree")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
