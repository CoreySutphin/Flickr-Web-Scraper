"""
    Module used to scrape photos from the Flickr website.
"""
import os
import re
import requests
import urllib
import logging
import json
import psycopg2
import boto3

from dataclasses import dataclass
from bs4 import BeautifulSoup
from multiprocessing import Pool

# Set up logging
format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")

# Spoofed headers to prevent the Flickr website from blocking our script for being a scraper.
SCRAPING_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "3600",
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0",
}

# Regex constants to find data in the HTML/JS returned from BeautifulSoup
LONGITUDE_REGEX = r'"longitude":(.*?),'
LATITUDE_REGEX = r'"latitude":(.*?),'
MODEL_EXPORT_SCRIPT_REGEX = r'"photos":{"_data":(\[.*?\])'


class FlickrImageManager:
    def upload_to_s3(self, images: list):
        """
            Upload the given images to S3 and return the list of images where the `s3_url` variable is updated with
            the link to the image in the S3 bucket.
        """
        bucket_name = os.environ.get("AWS_S3_BUCKET_NAME")
        if not bucket_name:
            raise Exception(
                "S3 bucket name must be provided under the AWS_S3_BUCKET_NAME environment variable."
            )

        session = boto3.Session()
        s3 = session.resource("s3")
        bucket = s3.Bucket(bucket_name)
        for image in images:
            try:
                r = requests.get(image.flickr_url, stream=True)
                filename = f"{image.flickr_id}.jpeg"
                bucket.upload_fileobj(r.raw, filename, ExtraArgs={"ACL": "public-read"})
                s3_url = f"https://{bucket_name}.s3.amazonaws.com/{filename}"
                image.s3_url = s3_url
            except Exception as e:
                logging.error(e)

        return images

    def upload_to_db(self, images: list):
        """
            Upload a list of Image objects to a RDS database.
            This assumes that there exists a `photos` table in the supplied database.
        """

        # Load in connection paramaters from environment variables.
        DB_USER = os.environ.get("DB_USER")
        DB_PASSWORD = os.environ.get("DB_PASSWORD")
        DB_HOST = os.environ.get("DB_HOST")
        DB_PORT = os.environ.get("DB_PORT")
        DB_NAME = os.environ.get("DB_NAME")

        db_creds = {
            "host": DB_HOST,
            "database": DB_NAME,
            "user": DB_USER,
            "password": DB_PASSWORD,
            "port": DB_PORT,
        }

        # If any required DB credentials are not present, raise an exception
        if any([val == None for val in db_creds.values()]):
            raise Exception(
                "RDS credentials must be provided through environment variables."
            )

        try:
            conn = psycopg2.connect(**db_creds)
            cursor = conn.cursor()
            insert_query = "INSERT INTO photos (flickr_id, flickr_user_id, flickr_url, s3_url, latitude, longitude) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (flickr_id) DO NOTHING;"
            cursor.executemany(insert_query, [image.to_tuple() for image in images])
            conn.commit()
        except Exception as e:
            logger.error(e)
        finally:
            cursor.close()
            conn.close()


@dataclass
class FlickrImage:
    flickr_id: str
    flickr_user_id: str = ""
    flickr_url: str = ""
    s3_url: str = ""
    latitude: float = None
    longitude: float = None

    # Manager class to handle database/S3 uploads
    manager = FlickrImageManager()

    def to_tuple(self):
        return (
            self.flickr_id,
            self.flickr_user_id,
            self.flickr_url,
            self.s3_url,
            self.latitude,
            self.longitude,
        )

    def __eq__(self, other):
        return self.flickr_id == other.flickr_id

    def __hash__(self):
        return hash(self.flickr_id)


class FlickrScraper:
    def __init__(self):
        self.base_url = "https://www.flickr.com/search/"

    def _extract_gps_metadata(self, image: FlickrImage):
        """
            The GPS metadata lives on the detail page of each photo(if it is shared at all).
            We will need to reach out to the detail page for each image to get this information.

            NOTE: Other methods have been tried to retrive this data, including retrieving the EXIF
            data present on the scraped images. It seems EXIF data is only preserved on original images,
            which aren't made available to public users.
        """
        detail_url = (
            f"https://www.flickr.com/photos/{image.flickr_user_id}/{image.flickr_id}/"
        )
        response = requests.get(detail_url, SCRAPING_HEADERS)
        detail_soup = BeautifulSoup(response.content, "html.parser")

        # Parse GPS information from the "modelExport" script
        model_export_script = detail_soup.find("script", {"class": "modelExport"})
        if model_export_script:
            latitude_match = re.search(LATITUDE_REGEX, model_export_script.string)
            longitude_match = re.search(LONGITUDE_REGEX, model_export_script.string)

            if latitude_match and longitude_match:
                latitude = float(latitude_match.group(1))
                longitude = float(longitude_match.group(1))
                return (latitude, longitude)

        return None

    def _extract_photo_objects_from_script(self, script: str):
        """
            Extract a list of photo objects from the `modelExport` script contained on the webpage.
        """
        photo_objects = []

        model_export_match = re.search(MODEL_EXPORT_SCRIPT_REGEX, script)
        if model_export_match:
            photo_objects_str = model_export_match.group(1)
            photo_objects = json.loads(photo_objects_str)

        return photo_objects

    def crawl_pages(self, query: str, start_page: int, end_page: int):
        """
            Crawl through a range of pages using the given query, extracting images
            from the JavaScript present on the page.
        """
        pid = os.getpid()
        counter = start_page
        images = []
        while counter < end_page:
            logging.info(f"Process {pid} processing page {counter}")
            params = {"text": query, "page": counter + 1}
            url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
            response = requests.get(url, SCRAPING_HEADERS)
            soup = BeautifulSoup(response.content, "html.parser")

            model_export_script = soup.find("script", {"class": "modelExport"})
            if model_export_script:
                photo_objects = self._extract_photo_objects_from_script(
                    model_export_script.string
                )

                if not photo_objects:
                    logging.warning(
                        f"Process {pid} failed to parse photos for page {counter}. Model Script: {model_export_script} - Photo Objects: {photo_objects}"
                    )
                    continue

                for photo in photo_objects:
                    if not photo or not photo.get("id"):
                        continue

                    url = photo.get("sizes").get("w").get("url")
                    image = FlickrImage(
                        flickr_id=photo.get("id"),
                        flickr_url=f"https:{url}",
                        flickr_user_id=photo.get("ownerNsid"),
                    )

                    # Extract GPS info for each image
                    gps_info = self._extract_gps_metadata(image)
                    if gps_info:
                        image.latitude = gps_info[0]
                        image.longitude = gps_info[1]

                    images.append(image)

            counter += 1

        return images

    def scrape(self, query: str, num_pages=1, num_cores=1):
        """
            Scrape the Flickr website with a given search query, number of pages to scrape, and number of
            cores/processes to use for scraping. Returns a list of FlickrImage objects containing the scraped
            data.
        """
        logging.info(
            f"Starting to scrape with query: {query} - num_pages: {num_pages} - num_cores: {num_cores}"
        )
        if num_pages < num_cores:
            raise Exception(
                "The number of pages to scrape must be >= the number of processes spawned"
            )

        # Each process will handle its own range of pages to scrape
        pool = Pool(num_cores)
        pages_per_core = int(num_pages / num_cores)
        images = []
        args = [
            [query, (x * pages_per_core), (x * pages_per_core) + pages_per_core]
            for x in range(num_cores)
        ]
        # Handle the case where pages cannot be evenly distributed to processes, throw the extras to the last process.
        if num_pages % num_cores != 0:
            remainder = num_pages % num_cores
            args[-1][2] += remainder

        for result in pool.starmap(self.crawl_pages, args):
            images += result

        # Close the Pool
        pool.close()

        logging.info(
            f"Finished scraping with query: {query} - num_pages: {num_pages} - num_cores: {num_cores}"
        )

        unique_images = set(images)
        logging.debug(f"Count of all images: {len(images)}")
        logging.debug(f"Count of unique images: {len(unique_images)}")
        return list(unique_images)
