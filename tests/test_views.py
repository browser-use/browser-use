import pytest

from browser_use.controller.views import SearchGoogleAction

class TestSearchGoogleAction:
    def test_search_google_action_valid_input(self):
        """
        Test that SearchGoogleAction correctly validates a valid input.
        """
        query = "Python programming"
        action = SearchGoogleAction(query=query)
        assert action.query == query

    def test_search_google_action_missing_query(self):
        """
        Test that SearchGoogleAction raises a validation error when the query is missing.
        """
        with pytest.raises(ValueError):
            SearchGoogleAction()