# Flickr-Web-Scraper

A Python library for scraping images from the Flickr website using BeautifulSoup, and then uploading them to S3/a Postgres database.


## Installation

Run the following from the root folder of the project to install the package.

```bash
pip install -e .
```

To utilize the S3/RDS utilities, relevant environment variables must be set in your virtual environment. They are listed below:

```bash
DB_USER = ""
DB_PASSWORD = ""
DB_HOST = ""
DB_PORT = ""
DB_NAME = ""

AWS_ACCESS_KEY_ID = ""
AWS_SECRET_ACCESS_KEY = ""
AWS_S3_BUCKET_NAME = ""
```

## Usage

Three main classes make up the bulk of the functionality.

`FlickrImage` - Python class for holding scraped images.

`FlickrImageManager` - Manager class used to upload `FlickrImage` objects to an S3 bucket/Postgres database.

`FlickrScraper` - This class contains the logic for parsing images from the Flickr website, returning the list of scraped images as `FlickrImage` objects.

#### Scraping Images

```python
from flickrscraper import FlickrScraper, FlickrImage

scraper = FlickrScraper()

images = scraper.scrape(query="paris", num_pages=10, num_cores=5)
print(images)

[FlickrImage(flickr_id='50929661533', flickr_user_id='73422502@N08', flickr_url='https://live.staticflickr.com/65535/50929661533_c47487ffd5_w.jpg', s3_url='https://flickr-scraper.s3.amazonaws.com/50929661533.jpeg', latitude=48.867477, longitude=2.329444), FlickrImage(flickr_id='50863024613', flickr_user_id='73422502@N08', flickr_url='https://live.staticflickr.com/65535/50863024613_e441f5c4fe_w.jpg', s3_url='https://flickr-scraper.s3.amazonaws.com/50863024613.jpeg', latitude=48.861666, longitude=2.289166),...]
```

#### Uploading to S3

```python
# Upload each image to S3 and update it to contain its S3 url
images = FlickrImage.manager.upload_to_s3(images)

# Upload the images to the RDS database
FlickrImage.manager.upload_to_db(images)
```

## Running Tests

To run all tests, use the following command from the root of the project:

```bash
python flickrscraper/tests.py
```