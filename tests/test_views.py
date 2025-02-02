import pytest

from browser_use.controller.views import SearchGoogleAction

def test_search_google_action_valid_input():
    """
    Test that SearchGoogleAction accepts a valid query string.
    This test ensures that the model correctly initializes with a proper query input.
    """
    query = "pytest testing"
    action = SearchGoogleAction(query=query)
    assert action.query == query