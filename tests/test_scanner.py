import unittest

from bs4 import BeautifulSoup

from src.scanner import _extract_cards, _page_links


class ScannerTests(unittest.TestCase):
    def test_extracts_stable_video_ids_and_absolute_urls(self):
        html = """
        <html><body><section>
          <div class="card">
            <a href="/video/62446/adn-582" title="Sample title">Watch</a>
          </div>
          <div class="card">
            <a href="/video/62447/xyz-100">Second video</a>
          </div>
        </section></body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_cards(soup, "https://javtiful.com/channel/s1-no1-style")
        self.assertEqual({item["source_id"] for item in result}, {"62446", "62447"})
        self.assertTrue(all(item["page_url"].startswith("https://javtiful.com/video/") for item in result))
        self.assertEqual(next(item for item in result if item["source_id"] == "62446")["title"], "Sample title")

    def test_ignores_external_video_links(self):
        html = """
        <section><div class="card">
          <a href="https://example.com/video/12">external</a>
        </div></section>
        """
        result = _extract_cards(BeautifulSoup(html, "html.parser"), "https://javtiful.com/channel/demo")
        self.assertEqual(result, [])

    def test_finds_next_pagination_link(self):
        html = """
        <nav class="pagination">
          <a href="/channel/demo?page=2" rel="next">Next</a>
        </nav>
        """
        result = _page_links(BeautifulSoup(html, "html.parser"), "https://javtiful.com/channel/demo")
        self.assertIn("https://javtiful.com/channel/demo?page=2", result)


if __name__ == "__main__":
    unittest.main()
