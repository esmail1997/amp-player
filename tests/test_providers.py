"""اختبارات مزوّدات الترجمة — بلا شبكة: كل طلبات HTTP مزوَّرة."""

from __future__ import annotations

import gzip
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ampplayer.providers import manager  # noqa: E402
from ampplayer.providers import opensubtitles_provider as osp  # noqa: E402
from ampplayer.providers.models import SubtitleResult  # noqa: E402

SRT_TEXT = (
    "1\n00:00:01,000 --> 00:00:03,000\nمرحبا بالعالم\n\n"
    "2\n00:00:04,000 --> 00:00:06,000\nسطر ثانٍ\n"
)
ASS_TEXT = "[Script Info]\nTitle: t\nScriptType: v4.00+\n\n" \
           "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, " \
           "MarginR, MarginV, Effect, Text\n"

LEGACY_ITEM = {
    "IDSubtitleFile": "1957488900",
    "IDSubtitle": "12345",
    "MovieName": "The Matrix",
    "MovieReleaseName": "The.Matrix.1999.BluRay.x264",
    "MovieYear": "1999",
    "MovieKind": "movie",
    "LanguageName": "Arabic",
    "SubLanguageID": "ara",
    "SeriesSeason": "0",
    "SeriesEpisode": "0",
    "SubDownloadsCnt": "47135",
    "SubRating": "8.4",
    "SubDownloadLink": "https://dl.opensubtitles.org/en/download/src-api/"
                       "vrf-abc/filead/1957488900.gz",
    "SubtitlesLink": "https://www.opensubtitles.org/en/subtitles/12345",
    "SubFileName": "The.Matrix.1999.BluRay.x264.srt",
}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._payload


class LegacyUrlTests(unittest.TestCase):
    def test_params_sorted_alphabetically(self):
        """الترتيب الأبجدي يمنع إعادة التوجيه (302) من الخادم."""
        url = osp._legacy_url(query="", imdb_id="tt0133093", lang="ara",
                              season="1", episode="2")
        self.assertEqual(
            url,
            "https://rest.opensubtitles.org/search/episode-2/imdbid-0133093/"
            "season-1/sublanguageid-ara",
        )

    def test_query_only(self):
        url = osp._legacy_url(query="matrix", lang="ara")
        self.assertEqual(
            url, "https://rest.opensubtitles.org/search/query-matrix/sublanguageid-ara"
        )

    def test_arabic_query_percent_encoded(self):
        url = osp._legacy_url(query="الحرمين", lang="ara")
        self.assertNotIn("الحرمين", url)
        self.assertTrue(url.endswith("/sublanguageid-ara"))
        self.assertIn("query-%D8%A7", url)

    def test_empty_when_no_params(self):
        self.assertEqual(osp._legacy_url(query="   ", lang=""), "")

    def test_zero_season_and_episode_omitted(self):
        url = osp._legacy_url(query="x", season="0", episode="0", lang="eng")
        self.assertNotIn("season", url)
        self.assertNotIn("episode", url)

    def test_imdb_normalization(self):
        self.assertEqual(osp._norm_imdb("tt0133093"), "0133093")
        self.assertEqual(osp._norm_imdb("133093"), "0133093")
        self.assertEqual(osp._norm_imdb("tt133093"), "0133093")
        self.assertEqual(osp._norm_imdb(""), "")


class MappingTests(unittest.TestCase):
    def test_maps_all_fields(self):
        r = osp._map_legacy_item(dict(LEGACY_ITEM))
        self.assertIsNotNone(r)
        self.assertEqual(r.site, "opensubtitles")
        self.assertEqual(r.title, "The Matrix")
        self.assertEqual(r.language_code, "ara")
        self.assertEqual(r.downloads, 47135)
        self.assertEqual(r.rating, 8.4)
        self.assertEqual(r.kind, "download")
        self.assertTrue(r.download_url.startswith("https://"))
        # صفر الموسم/الحلقة يعني «فيلم» لا «موسم 0»
        self.assertEqual(r.season, "")
        self.assertEqual(r.episode, "")

    def test_series_values_kept(self):
        item = dict(LEGACY_ITEM, SeriesSeason="1", SeriesEpisode="2",
                    MovieKind="episode")
        r = osp._map_legacy_item(item)
        self.assertEqual(r.season, "1")
        self.assertEqual(r.episode, "2")

    def test_item_without_download_link_skipped(self):
        item = dict(LEGACY_ITEM, SubDownloadLink="")
        self.assertIsNone(osp._map_legacy_item(item))


class SearchTests(unittest.TestCase):
    def setUp(self):
        # نعزل الاختبار عن أي مفتاح حقيقي في بيئة المستخدم
        self._patchers = [
            mock.patch.object(osp, "_load_key", return_value=""),
            mock.patch.object(osp, "make_session"),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def test_search_without_key_returns_results(self):
        seen = {}

        def fake_get(session, url, **kw):
            seen["url"] = url
            return _FakeResponse(200, payload=[dict(LEGACY_ITEM)])

        with mock.patch.object(osp, "get", side_effect=fake_get):
            out = osp.search(query="matrix", lang="ara")

        self.assertEqual(out.error, "")
        self.assertEqual(len(out.results), 1)
        self.assertFalse(out.needs_manual)
        self.assertIn("query-matrix", seen["url"])
        self.assertIn("sublanguageid-ara", seen["url"])

    def test_imdb_search_builds_padded_imdb_param(self):
        seen = {}

        def fake_get(session, url, **kw):
            seen["url"] = url
            return _FakeResponse(200, payload=[dict(LEGACY_ITEM)])

        with mock.patch.object(osp, "get", side_effect=fake_get):
            out = osp.search(query="", imdb_id="tt0133093", lang="ara")

        self.assertEqual(out.error, "")
        self.assertIn("imdbid-0133093", seen["url"])

    def test_http_error_without_key_falls_back_to_manual(self):
        def fake_get(session, url, **kw):
            return _FakeResponse(503, payload=None)

        with mock.patch.object(osp, "get", side_effect=fake_get):
            out = osp.search(query="matrix", lang="ara")

        self.assertEqual(out.error, "http_503")
        self.assertTrue(out.needs_manual)
        self.assertIn("opensubtitles.com", out.manual_url)
        self.assertEqual(out.results, [])

    def test_network_exception_becomes_error_not_crash(self):
        def fake_get(session, url, **kw):
            raise OSError("boom")

        with mock.patch.object(osp, "get", side_effect=fake_get):
            out = osp.search(query="matrix", lang="ara")

        self.assertTrue(out.error.startswith("search_failed"))
        self.assertTrue(out.needs_manual)

    def test_non_list_payload_rejected(self):
        def fake_get(session, url, **kw):
            return _FakeResponse(200, payload={"unexpected": True})

        with mock.patch.object(osp, "get", side_effect=fake_get):
            out = osp.search(query="matrix", lang="ara")

        self.assertEqual(out.error, "bad_payload")

    def test_empty_query_without_imdb(self):
        out = osp.search(query="   ", lang="ara")
        self.assertEqual(out.error, "empty_query")

    def test_resolve_accepts_url_and_file_id(self):
        direct = SubtitleResult(download_url="https://x.test/file.gz")
        self.assertEqual(osp.resolve(direct), "https://x.test/file.gz")
        fileid = SubtitleResult(download_url="1957488900")
        self.assertEqual(osp.resolve(fileid), "1957488900")
        self.assertIsNone(osp.resolve(SubtitleResult(download_url="")))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="amp_dl_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _result(url):
        return SubtitleResult(site=osp.SITE, site_name=osp.SITE_NAME,
                              title="Some Movie", download_url=url)

    def test_gzip_srt_is_decompressed(self):
        url = "https://dl.opensubtitles.org/x/filead/1.gz"

        def fake_get(session, target, **kw):
            return _FakeResponse(200, content=gzip.compress(SRT_TEXT.encode("utf-8")),
                                 headers={"Content-Type": "application/x-gzip"})

        with mock.patch.object(manager, "get", side_effect=fake_get):
            path = manager.download(self._result(url), dest_dir=self.tmp)

        self.assertIsNotNone(path)
        self.assertEqual(path.suffix, ".srt")
        self.assertEqual(path.read_text(encoding="utf-8"), SRT_TEXT)

    def test_gzip_ass_detected_by_content(self):
        url = "https://dl.opensubtitles.org/x/filead/2.gz"

        def fake_get(session, target, **kw):
            return _FakeResponse(200, content=gzip.compress(ASS_TEXT.encode("utf-8")),
                                 headers={"Content-Type": "application/octet-stream"})

        with mock.patch.object(manager, "get", side_effect=fake_get):
            path = manager.download(self._result(url), dest_dir=self.tmp)

        self.assertIsNotNone(path)
        self.assertEqual(path.suffix, ".ass")

    def test_corrupt_gzip_returns_none(self):
        url = "https://dl.opensubtitles.org/x/filead/3.gz"

        def fake_get(session, target, **kw):
            return _FakeResponse(200, content=b"\x1f\x8b not really gzip")

        with mock.patch.object(manager, "get", side_effect=fake_get):
            path = manager.download(self._result(url), dest_dir=self.tmp)

        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
