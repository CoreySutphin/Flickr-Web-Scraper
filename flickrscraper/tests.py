import unittest

from flickr_scraper import FlickrScraper, FlickrImage


class TestFlickrScraper(unittest.TestCase):
    def setUp(self):
        self.scraper = FlickrScraper()

    def test_scrape_image(self):
        results = self.scraper.scrape(query="paris")
        self.assertNotEqual(len(results), 0)
        self.assertEqual(type(results[0]), FlickrImage)

    def test_scrape_image_multiple_pages(self):
        results = self.scraper.scrape(query="paris", num_pages=10, num_cores=3)
        self.assertNotEqual(len(results), 0)
        self.assertEqual(type(results[0]), FlickrImage)

    def test_process_limit(self):
        with self.assertRaises(Exception):
            results = self.scraper.scrape(query="paris", num_pages=1, num_cores=5)


if __name__ == "__main__":
    unittest.main()
