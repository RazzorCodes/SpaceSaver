import sys
import unittest.mock

from classifier import classify
from models import MediaType

def test_classify_movie():
    with unittest.mock.patch('classifier._probe_title', return_value=None):
        media_type, title, year = classify("/movies/Inception.2010.1080p.Bluray.mkv")
        assert media_type == MediaType.MOVIE
        assert title == "Inception"
        assert year == "2010"

def test_classify_tv():
    with unittest.mock.patch('classifier._probe_title', return_value=None):
        media_type, title, ep = classify("/tv/Breaking.Bad.S01E01.720p.mkv")
        assert media_type == MediaType.TV
        assert title == "Breaking Bad"
        assert ep == "S01E01"

test_classify_movie()
test_classify_tv()
print('Classifier tests passed!')
