import sys
from models import MediaFile, MediaType, FileStatus

def test_mediafile_creation():
    mf = MediaFile.new(
        file_hash="dummyhash123",
        source_path="/source/movie.mkv",
        dest_path="/dest/movie.mkv",
        media_type=MediaType.MOVIE,
        clean_title="A Great Movie",
        year_or_episode="2024",
    )
    
    assert mf.file_hash == "dummyhash123"
    assert mf.status == FileStatus.PENDING
    assert mf.progress == 0.0

def test_mediafile_to_dict():
    mf = MediaFile.new(
        file_hash="dummyhash123",
        source_path="/source/movie.mkv",
        dest_path="/dest/movie.mkv",
        media_type=MediaType.MOVIE,
        clean_title="A Great Movie",
        year_or_episode="2024",
    )
    d = mf.to_dict()
    assert d["name"] == "A Great Movie 2024"
    assert d["status"] == "pending"
    assert d["progress"]["frame"]["now"] == 0
    assert d["progress"]["frame"]["total"] == 0

test_mediafile_creation()
test_mediafile_to_dict()
print('Models tests passed!')
