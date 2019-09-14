__author__ = 'Nicholas McKinney'

import argparse
import getpass
import json
import logging
import os
import requests
import time
import traceback


from bs4 import BeautifulSoup

ConferenceIds = {
    "DEFCON24": 32,
    "DEFCON25": 41,
    "DEFCON26": 54,
    "DEFCON27": 71,
    "DEFCON27-VILLAGE": 72,
    "DEFCON26-VILLAGE": 67,
    "BSidesLV2016": 39,
    "BlackHatUSA2017": 40,
    "BlackHatUSA2018": 53,
    "BlackHatUSA2019": 70,
}
AllowedChoices = ConferenceIds.keys()

PLAYLIST_URL = "https://www.sok-media.com/player?action=get_playlist&conf_id={conference}"
VIDEO_URL = "https://www.sok-media.com/player?session_id={video}&action=get_video"
BASE_URL = "https://www.sok-media.com"
LOGIN_URL = "https://www.sok-media.com/node?destination=node"

logger = logging.getLogger("SOK-Media-Downloader")
logger.setLevel("INFO")
stream_handler = logging.StreamHandler()
stream_handler.setLevel("INFO")
logger.addHandler(stream_handler)


class Content:
    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, value):
        self._id = value

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value


class Client:
    def __init__(self, username, password, directory, delay, debug=False):
        self._username = username
        self._password = password
        self._directory = directory
        self._delay = delay
        self._debug = debug
        self._session = requests.Session()
        self._cookies = None

    def login(self):
        r = self._session.get(BASE_URL)
        if self.failed(r):
            logger.error("[*] Failed to access login page")
            raise ValueError("Failed connection")
        soup = BeautifulSoup(r.content, 'html.parser')
        div = soup.find(id="page_container")
        inputs = div.find_all("input", type="hidden")
        payload = {
            "name" : self._username,
            "pass": self._password,
            "op": "Log+in"
        }
        for input in inputs:
            payload[input.attrs['name']] = input.attrs['value']
        r = requests.post(LOGIN_URL, data=payload, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        if len(r.history):
            cookies = requests.utils.dict_from_cookiejar(r.history[0].cookies)
            self._cookies = cookies
            return self._cookies
        raise ValueError("Unable to login")

    def get_video(self, video):
        if self._cookies is None:
            raise ValueError("Must login 1st")
        logger.info("[*] Downloading video: %s", video.name)
        video_filename = video.name.replace("/", "") + '.mp4'
        dl_path = os.path.join(self._directory, video_filename)
        if os.path.exists(dl_path):
            logger.warning("[!] Video %s already exists. Skipping...", video_filename)
            return
        r = self._session.get(VIDEO_URL.format(video=video.id), cookies=self._cookies)
        if self.failed(r):
            logger.error("[!] Failed to get download URL for: {title}".format(title=video.name))
            return
        content = json.loads(r.content.decode("utf8"))
        logger.info("[v] Download URL (only works for ~3hr): %s", content['url'])
        stream = self._session.get(content['url'], stream=True)
        if self.failed(stream):
            logger.error("[!] Failed to get stream for: {title}".format(title=video.name))
            return
        with open(dl_path, 'wb') as fh:
            for chunk in stream.iter_content(chunk_size=4096):
                fh.write(chunk)
        logger.info("[*] Downloaded video: %s to %s", video.name, dl_path)
        return dl_path

    def _make_vid(self, d):
        c = Content()
        c.id = d['sess_id']
        c.name = d['sess_data']['session_name']
        return c

    def get_playlist(self, conference):
        if self._cookies is None:
            raise ValueError("Must login 1st")
        logger.info("[*] Getting playlist videos for {conference}".format(conference=conference.name))
        r = self._session.get(PLAYLIST_URL.format(conference=conference.id), cookies=self._cookies)
        if self.failed(r):
            logger.error("[!] Failed to get video playlist information for {conference}".format(conference=conference.name))
            return
        content = json.loads(r.content.decode('utf8'))
        if self._debug:
            with open(os.path.join(self._directory, "playlist.json"), "w") as fh:
                json.dump(content, fh, indent=2)
        videos = [self._make_vid(d) for d in content['data']]
        logger.info('[*] Retrieved %d videos from conference %s' % (len(videos), conference.name))
        return videos

    def failed(self, resp):
        return True if resp.status_code != 200 else False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('conferences', choices=AllowedChoices, nargs="+")
    parser.add_argument('output_dir')
    parser.add_argument('username')
    parser.add_argument("-d", "--delay", type=int, default=5,
            help="Delay between video downloads in seconds (default 5)")
    parser.add_argument("-D", "--debug", action="store_true")

    # Accept password command line (as previously done) or via getpass
    parser_pass = parser.add_mutually_exclusive_group(required=True)
    parser_pass.add_argument('-p', '--password')
    parser_pass.add_argument('-P', '--prompt-pass', action="store_true",
            help="Prompt for password")

    args = parser.parse_args()

    if args.prompt_pass:
        password = getpass.getpass()
    else:
        password = args.password

    for conference_name in args.conferences:
        logger.info("[*] Start processing conference: %s", conference_name)
        conference_dir = os.path.join(args.output_dir, conference_name)
        if not os.path.exists(conference_dir):
            os.mkdir(conference_dir)
        c = Content()
        c.id = ConferenceIds[conference_name]
        c.name = conference_name
        cli = Client(
                username=args.username,
                password=password,
                directory=conference_dir,
                delay=args.delay,
                debug=args.debug)
        cli.login()
        videos = cli.get_playlist(c)
        for video in videos:
            for retries in range(3):
                try:
                    cli.get_video(video)
                    break
                except Exception as error:
                    logger.info('Error trying to download: %s, on retry %d',
                            str(error), retries)
                finally:
                    if args.delay > 0:
                        logger.info('Sleeping for %d sec(s)', args.delay)
                        time.sleep(args.delay)
        logger.info("[^] Done downloading for conference: %s", conference_name)


if __name__ == '__main__':
    main()
