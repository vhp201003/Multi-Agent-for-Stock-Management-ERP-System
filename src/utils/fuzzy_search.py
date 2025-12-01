from difflib import SequenceMatcher


def fuzzy_search_best_match(query: str, candidates: list[str], threshold: float = 0.6) -> str | None:
	"""
	Find the best matching string from a list of candidates using fuzzy search.

	Args:
		query: The search query string
		candidates: List of candidate strings to search through
		threshold: Minimum similarity score (0.0 to 1.0)

	Returns:
		Best matching candidate or None if no match above threshold

	Example:
		>>> candidates = ["Apple iPhone 13", "Samsung Galaxy S21", "Apple iPhone 12"]
		>>> fuzzy_search_best_match("iphone 13", candidates)
		'Apple iPhone 13'
	"""
	if not query or not candidates:
		return None

	query_lower = query.lower().strip()
	best_match = None
	best_score = threshold

	for candidate in candidates:
		candidate_lower = candidate.lower().strip()
		similarity = SequenceMatcher(None, query_lower, candidate_lower).ratio()

		if similarity > best_score:
			best_score = similarity
			best_match = candidate

	return best_match
