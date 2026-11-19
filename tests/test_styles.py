"""Каталог стилей и память повторов (core/styles.py) без сети и без боевой БД.

    python -m unittest tests.test_styles
"""
import datetime
import json
import os
import random
import tempfile
import unittest
from unittest import mock

from core import pipeline, prompt_batches, prompts, styles


def style(n, section="s1", suits=("architecture",), figurative=2, fame=2, text=False):
    return {"id": f"st{n}", "name": f"Style {n}", "kind": "artist", "medium": "oil on canvas",
            "region": "France", "era": "1900s", "features": f"visible traits {n}",
            "fame": fame, "figurative": figurative, "text": text, "suits": list(suits),
            "section": section}


class StylesBase(unittest.TestCase):
    def setUp(self):
        self.real_catalog = styles.CATALOG_PATH
        self.dir = tempfile.TemporaryDirectory()
        self.catalog_path = os.path.join(self.dir.name, "styles.json")
        self.db_path = os.path.join(self.dir.name, "db.sqlite")
        self.real_ru = styles.RU_PATH
        self.ru_path = os.path.join(self.dir.name, "styles_ru.json")
        patches = [mock.patch.object(styles, "CATALOG_PATH", self.catalog_path),
                   mock.patch.object(styles, "RU_PATH", self.ru_path),
                   mock.patch.object(styles, "DB_PATH", self.db_path)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        styles._cache.update(mtime=None, data=None)
        styles._ru_cache.update(mtime=None, data={})
        self.addCleanup(self.dir.cleanup)
        self.now = datetime.datetime(2026, 11, 19, 4, 30)

    def write(self, items):
        with open(self.catalog_path, "w", encoding="utf-8") as file:
            json.dump({"styles": items}, file)
        styles._cache.update(mtime=None, data=None)


class EligibleTests(StylesBase):
    def test_filters(self):
        catalog = [style(1), style(2, suits=("nature",)), style(3, figurative=0),
                   style(4, fame=1), style(5, text=True)]
        ids = lambda cfg: [s["id"] for s in styles.eligible(catalog, cfg)]  # noqa: E731
        self.assertEqual(ids({"suits": ["architecture"]}), ["st1", "st4", "st5"])
        self.assertEqual(ids({"suits": ["architecture"], "min_fame": 2}), ["st1", "st5"])
        self.assertEqual(ids({"suits": ["architecture"], "text": "exclude"}), ["st1", "st4"])
        self.assertEqual(ids({"min_figurative": 0}), ["st1", "st2", "st3", "st4", "st5"])
        self.assertEqual(ids({}), ["st1", "st2", "st4", "st5"])   # абстракция — только по явной настройке


class ChooseStyleTests(StylesBase):
    def test_no_repeat_until_pool_exhausted_then_oldest(self):
        self.write([style(n, section=f"s{n}") for n in range(1, 6)])
        rng = random.Random(1)
        picked = [styles.choose_style("hidream", {}, now=self.now + datetime.timedelta(days=d), rng=rng)["id"]
                  for d in range(5)]
        self.assertEqual(len(set(picked)), 5)
        sixth = styles.choose_style("hidream", {}, now=self.now + datetime.timedelta(days=5), rng=rng)
        self.assertEqual(sixth["id"], picked[0])    # самый давний из выпадавших

    def test_repeat_window_expires(self):
        self.write([style(1), style(2)])
        first = styles.choose_style("hidream", {"repeat_days": 10, "global_days": 0}, now=self.now)
        later = [styles.choose_style("hidream", {"repeat_days": 10, "global_days": 0},
                                     now=self.now + datetime.timedelta(days=30 + d))["id"] for d in range(2)]
        self.assertIn(first["id"], later)

    def test_other_jobs_style_of_these_days_is_avoided(self):
        self.write([style(1), style(2)])
        a = styles.choose_style("hidream", {}, now=self.now)
        for _ in range(5):
            # стили того же раздела — правило разделов здесь уступает
            b = styles.choose_style(f"job{_}", {"repeat_days": 0}, now=self.now)
            self.assertNotEqual(a["id"], b["id"])
            styles._connect().execute("DELETE FROM render_usage WHERE job_key LIKE 'job%'").connection.commit()

    def test_section_not_repeated_in_last_runs(self):
        self.write([style(1, "japan"), style(2, "japan"), style(3, "dutch"), style(4, "dutch"),
                    style(5, "russia"), style(6, "russia")])
        rng = random.Random(7)
        sections = []
        for d in range(3):
            s = styles.choose_style("hidream", {"section_runs": 2}, now=self.now + datetime.timedelta(days=d), rng=rng)
            sections.append(s["section"])
        self.assertEqual(len(set(sections)), 3)

    def test_without_job_key_no_memory(self):
        self.write([style(1)])
        self.assertEqual(styles.choose_style(None, {}, now=self.now)["id"], "st1")
        self.assertEqual(styles._recent("SELECT COUNT(*) FROM render_usage", ())[0][0], 0)

    def test_empty_catalog(self):
        self.assertIsNone(styles.choose_style("hidream", {}, now=self.now))

    def test_memory_failure_does_not_break_choice(self):
        self.write([style(1)])
        with mock.patch.object(styles, "DB_PATH", os.path.join(self.dir.name, "нет", "db.sqlite")):
            self.assertEqual(styles.choose_style("hidream", {}, now=self.now)["id"], "st1")


class FormatTests(StylesBase):
    def test_format(self):
        line = styles.format_style(style(1), {})
        self.assertEqual(line, "Style 1 (oil on canvas; France, 1900s) — visible traits 1")
        self.assertTrue(styles.format_style(style(2, text=True), {"text": "inscription"}).endswith("[надпись]"))
        self.assertIn("только его графику", styles.format_style(style(3, text=True), {}))
        noted = dict(style(4), note="Do not reproduce trademark characters.")
        self.assertTrue(styles.format_style(noted, {}).endswith(
            "visible traits 4 (Caution: Do not reproduce trademark characters.)"))

    def test_real_catalog_is_valid(self):
        """data/styles.json в репозитории: поля на месте, id уникальны, каждой задаче хватит стилей."""
        from core.jobs import _default_jobs
        with mock.patch.object(styles, "CATALOG_PATH", self.real_catalog):
            styles._cache.update(mtime=None, data=None)
            catalog = styles.load_catalog()
        self.assertGreater(len(catalog), 1000)
        self.assertEqual(len({s["id"] for s in catalog}), len(catalog))
        for s in catalog:
            self.assertTrue(s["name"] and len(s["features"].split()) >= 8 and s["suits"], s["id"])
        for key, job in _default_jobs().items():
            cfg = job.get("llm", {}).get("styles")
            if cfg is not None:
                self.assertGreater(len(styles.eligible(catalog, cfg)), 365, key)


class ThemeTests(StylesBase):
    def test_recent_themes_avoided(self):
        rng = random.Random(3)
        got = [styles.choose_theme("qwen", 10, now=self.now + datetime.timedelta(days=d), rng=rng) for d in range(5)]
        self.assertEqual(len(set(got)), 5)      # половина из 10 — без повторов
        got = [styles.choose_theme("qwen", 4, runs=3, rng=rng) for _ in range(8)]
        for n in range(3, 8):
            self.assertNotIn(got[n], got[n - 3:n])


class RenderTests(StylesBase):
    def test_render_with_styles(self):
        self.write([style(1, text=True)])
        out = prompts.render_user_prompt("Тема {random_theme}. Стиль: {random_style}", max_theme=50,
                                         job_key="qwen", styles={"text": "inscription"}, now=self.now)
        self.assertIn("Стиль: Style 1 (oil on canvas; France, 1900s) — visible traits 1 [надпись]", out)
        kinds = sorted(r[0] for r in styles._recent("SELECT kind FROM render_usage WHERE job_key='qwen'", ()))
        self.assertEqual(kinds, ["style", "theme"])

    def test_render_without_styles_is_unchanged(self):
        out = prompts.render_user_prompt("Тема {random_theme}", max_theme=50)
        self.assertRegex(out, r"^Тема \d+$")
        self.assertEqual(styles._recent("SELECT COUNT(*) FROM render_usage", ())[0][0], 0)

    def test_style_placeholder_with_empty_catalog_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            prompts.render_user_prompt("{random_style}", job_key="qwen", styles={})

    def test_style_kwargs(self):
        self.assertEqual(prompt_batches.style_kwargs("qwen", {"max_theme": 50}), {})
        self.assertEqual(prompt_batches.style_kwargs("qwen", {"styles": {"suits": ["people"]}}),
                         {"job_key": "qwen", "styles": {"suits": ["people"]}})

    def test_pipeline_render_uses_job_styles(self):
        self.write([style(1, suits=("people",)), style(2, suits=("nature",))])
        job = {"llm": {"max_theme": 50, "styles": {"suits": ["people"]}}}
        with mock.patch.object(pipeline, "_generate_text", return_value="текст"):
            _, user, _ = pipeline._render_and_generate(job, {"system": "s", "user": "{random_style}"}, "qwen")
        self.assertTrue(user.startswith("Style 1 "))
        self.assertEqual(styles._recent("SELECT job_key, value FROM render_usage WHERE kind='style'", ()),
                         [("qwen", "st1")])


class CaptionTests(StylesBase):
    def write_ru(self, data):
        with open(self.ru_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)
        styles._ru_cache.update(mtime=None)

    def test_find_in_prompt(self):
        items = [style(1), style(12), dict(style(3), name="Style 1 (Paris)", medium="", region="", era="")]
        self.write(items)
        text = "Тема 4.\nСтиль: " + styles.format_style(items[1], {}) + "\nРакурс 2"
        self.assertEqual(styles.find_in_prompt(text)["id"], "st12")
        self.assertEqual(styles.find_in_prompt("Стиль: " + styles.format_style(items[2], {}))["id"], "st3")
        self.assertIsNone(styles.find_in_prompt("Стиль: Style 7 (oil) — traits"))
        self.assertIsNone(styles.find_in_prompt(""))

    def test_caption_russian_artist_keeps_original_name(self):
        self.write_ru({"st1": {"name": "Стиль Один", "medium": "масло, холст", "where": "Франция, 1900-е"}})
        self.assertEqual(styles.caption(dict(style(1), name="Style 1 (elder)")),
                         "🎨 Стиль: Стиль Один (Style 1) — масло, холст; Франция, 1900-е")
        self.assertEqual(styles.caption(dict(style(1), kind="school")),
                         "🎨 Стиль: Стиль Один — масло, холст; Франция, 1900-е")
        self.write_ru({"st1": {"name": "Стиль Один, поздний", "medium": "масло", "where": ""},
                       "st2": {"name": "Стиль Два (пастели)", "medium": "", "where": "Франция"}})
        self.assertEqual(styles.caption(dict(style(1), name="Style 1, late")),
                         "🎨 Стиль: Стиль Один (Style 1), поздний — масло")
        self.assertEqual(styles.caption(dict(style(2), name="Style 2, pastels")),
                         "🎨 Стиль: Стиль Два (пастели) — Франция")

    def test_caption_without_translation_is_english(self):
        self.assertEqual(styles.caption(style(2)), "🎨 Стиль: Style 2 — oil on canvas; France, 1900s")

    def test_pipeline_caption(self):
        self.write([style(1)])
        self.write_ru({"st1": {"name": "Стиль Один", "medium": "масло", "where": "Франция"}})
        user = "Стиль: " + styles.format_style(style(1), {})
        job = {"llm": {"styles": {}}, "publish": {}}
        self.assertEqual(pipeline._style_caption("k", job, user),
                         "🎨 Стиль: Стиль Один (Style 1) — масло; Франция")
        self.assertIsNone(pipeline._style_caption("k", {"llm": {}}, user))
        self.assertIsNone(pipeline._style_caption("k", dict(job, publish={"style_caption": False}), user))
        self.assertIsNone(pipeline._style_caption("k", job, "Стиль: что-то другое"))
        with mock.patch.object(styles, "caption", side_effect=KeyError("id")):
            self.assertIsNone(pipeline._style_caption("k", job, user))

    def test_real_catalog_found_and_translated(self):
        """Каждый стиль data/styles.json находится по своей строке в промпте и имеет перевод."""
        with mock.patch.object(styles, "CATALOG_PATH", self.real_catalog), \
                mock.patch.object(styles, "RU_PATH", self.real_ru):
            styles._cache.update(mtime=None, data=None)
            catalog = styles.load_catalog()
            ru = styles.load_ru()
            missing = [s["id"] for s in catalog if not (ru.get(s["id"]) or {}).get("name")]
            self.assertEqual(missing, [])
            for s in random.Random(5).sample(catalog, 120):
                for cfg in ({}, {"text": "inscription"}):
                    text = "Тема 3.\nСтиль: " + styles.format_style(s, cfg) + "\n"
                    self.assertEqual(styles.find_in_prompt(text, catalog)["id"], s["id"])
                self.assertTrue(styles.caption(s).startswith(
                    "🎨 Стиль: " + ru[s["id"]]["name"].split(",")[0]), s["id"])


if __name__ == "__main__":
    unittest.main()
