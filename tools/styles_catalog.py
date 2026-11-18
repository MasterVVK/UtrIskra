"""Каталог стилей data/styles.json: генерация разделов через Claude Opus и сборка.

Запуск из корня проекта (после set -a; . ./.env; set +a):
  .venv/bin/python tools/styles_catalog.py sections   # разделы → storage/styles_raw/s*.json (готовые пропускаются)
  .venv/bin/python tools/styles_catalog.py existing   # стили из existing.json, которых нет в разделах → e*.json
  .venv/bin/python tools/styles_catalog.py build      # склейка, дубли, проверка → data/styles.json

existing.json (необязательный) — стили прежних таблиц промптов: [{"style", "section", ...}].
Подробности — docs/styles.md.
"""
import concurrent.futures as cf
import datetime
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config  # noqa: F401,E402
from config import BASE_STORAGE_PATH  # noqa: E402
from providers.llm.base import build_llm_provider  # noqa: E402

RAW = os.path.join(BASE_STORAGE_PATH, "styles_raw")
OUT = os.path.join(ROOT, "data", "styles.json")

CFG = {"type": "anthropic", "model": "claude-opus-5-5", "effort": "high", "max_tokens": 48000}

SUITS = ["architecture", "landscape", "nature", "objects", "people", "crowd", "story", "festival", "north"]

SYSTEM = """You build a reference catalogue of visual styles for an automated illustration channel. Each day a language model receives ONE style from this catalogue (chosen at random by code) and writes an image-generator prompt in that style. Image generators (HiDream, Qwen-Image, Z-Image, ERNIE, MOSS, MiniMax, gpt-image, YandexART) often do not know an artist's name, so every entry must carry its own visible description that lets a generator reproduce the look without knowing the name.

Return ONLY a JSON array (no markdown fences, no commentary). Each element:
{
  "name": "how the style is named inside an English prompt: an artist ('Nicolas de Staël'), a school or tradition with its place and period ('Persian miniature, Safavid Tabriz school'), a technique ('Japanese woodblock print, shin-hanga'), a movement ('Precisionism')",
  "kind": "artist | school | movement | tradition | technique",
  "medium": "physical medium and support, short, English (e.g. 'oil on canvas, palette knife', 'colour woodcut on washi', 'gouache on board', 'stained glass')",
  "region": "country or region, English",
  "era": "period, English (e.g. '1950s', 'late 16th century', '12th–14th c.')",
  "features": "18–40 English words of VISIBLE traits only, so a generator can paint it: surface and material, line or brushwork or mark-making, how space and depth are built, typical palette, how figures/objects are drawn. No artwork titles, no biography, no praise words (no 'masterful', 'iconic', 'stunning'), no 'in the style of'.",
  "fame": 3 if a household name that common image models surely know | 2 if well known in art history or design | 1 if specialist or regional,
  "figurative": 2 if representational | 1 if stylised or decorative but recognisable | 0 if abstract or non-objective,
  "text": true only if the style is inseparable from lettering (posters, comics with balloons, illuminated script pages, maps, calligraphy, signage); otherwise false,
  "suits": a subset of ["architecture","landscape","nature","objects","people","crowd","story","festival","north"] — subjects this style renders convincingly:
     architecture = buildings, streets, interiors; landscape = terrain, sea, sky, places; nature = animals, birds, insects, plants seen close; objects = still life, things on a table or shelf; people = a few people at work or in daily life; crowd = large panoramas with many small figures; story = myths, fairy tales, legends, historical episodes with characters; festival = celebrations, rituals, costumes, dance; north = the style is rooted in Russia, Slavic, Baltic, Nordic, Finno-Ugric, Siberian or Arctic cultures,
  "note": "optional short caution, otherwise empty string"
}

Rules:
- Only artists who are no longer alive. No living artists, and no active commercial studios, brands or franchises (Disney, Pixar, Ghibli, Marvel, etc.): describe such looks as a period and technique instead ('hand-painted cel animation of 1940s American studios').
- Leave out practices that are sacred or restricted to their communities (Navajo sand painting, Aboriginal sacred designs and similar); secular folk and decorative traditions are welcome.
- Every entry must be distinct from the others in the array; prefer variety — major names AND lesser-known masters, women artists, regional schools outside the usual canon, crafts and printmaking techniques.
- Accuracy matters more than count: do not invent artists or traditions; features must truly describe the style.
- Give between 40 and 60 entries for the section."""

SECTIONS = [
    "Medieval European art: Romanesque and Gothic painting, illuminated manuscripts (as imagery), stained glass, tapestry, frescoes",
    "Early Renaissance and Northern Renaissance painters (Italy, Flanders, Germany, 14th–16th c.)",
    "High Renaissance, Mannerism and Venetian painting (16th c.)",
    "Baroque painting outside the Netherlands: Italy, Spain, France, Flanders (17th c.)",
    "Dutch Golden Age: landscape, townscape, interiors, genre, still life, marine (17th c.)",
    "Rococo, Enlightenment and 18th-century painting and vedute across Europe",
    "Romanticism and early 19th-century landscape and history painting (Europe and America)",
    "Realism, academic and Salon painting, Barbizon, Düsseldorf, Hudson River and other 19th-c. schools",
    "Impressionism and its circle worldwide (France, Scandinavia, Spain, Italy Macchiaioli, America, Australia Heidelberg)",
    "Post-Impressionism, Neo-Impressionism, Pont-Aven, Nabis",
    "Symbolism, Pre-Raphaelites, Aestheticism, fin-de-siècle painting",
    "Art Nouveau, Vienna Secession, Jugendstil, Arts and Crafts — painting, graphics and decorative art",
    "Fauvism and Expressionism (Die Brücke, Der Blaue Reiter, Nordic and other expressionists)",
    "Cubism, Futurism, Orphism, Vorticism, Rayonism and related early avant-garde",
    "Russian and Soviet art: Peredvizhniki, Mir iskusstva, Russian avant-garde, Soviet painting, Severe Style, Soviet book illustration",
    "Russian, Ukrainian, Belarusian and other Slavic folk and decorative arts as imagery: Palekh, Mstyora, Kholui, Fedoskino lacquer, Khokhloma, Gzhel, Zhostovo, lubok, Mezen and Northern Dvina painting, Petrykivka, wycinanki",
    "Byzantine, Orthodox and Eastern Christian art: icons of Novgorod, Pskov, Moscow, Stroganov schools, Armenian and Georgian manuscripts, Coptic and Ethiopian church painting",
    "Nordic, Baltic and Finno-Ugric art: Golden Age of Danish painting, Skagen, Finnish national romanticism, Swedish and Norwegian painters, Baltic modernists, Sami duodji motifs (secular)",
    "Dada, Surrealism, Metaphysical painting, Magic Realism",
    "New Objectivity, Precisionism, American Scene, Regionalism, Social Realism, WPA",
    "Abstract and geometric abstraction, De Stijl, Bauhaus painting, Suprematism, Constructivism, Colour Field, Abstract Expressionism (deceased artists only)",
    "Mid-century and later 20th-century figurative painting, Pop art, Photorealism, Op art (deceased artists only)",
    "Naïve, folk, self-taught and outsider painters worldwide (Henri Rousseau, Niko Pirosmani, Maria Prymachenko, Haitian, Croatian Hlebine and others)",
    "Golden Age of illustration (1880–1940): European and American book and magazine illustrators",
    "Children's book illustration worldwide in the 20th century (deceased illustrators), including Soviet, Czech, Polish, Scandinavian, Japanese",
    "Comics and graphic narrative traditions: Franco-Belgian ligne claire, early American newspaper strips, Italian fumetti, Argentine historieta, gekiga — as drawing styles (deceased artists or movements)",
    "Animation traditions as visual styles: hand-painted cel animation by period, Soviet Soyuzmultfilm look, Czech puppet film, Zagreb school, cut-out animation, paint-on-glass, stop-motion clay (described as periods and techniques, no brands)",
    "Poster and graphic design movements: Art Deco posters, Plakatstil, Soviet Constructivist, Polish Poster School, Swiss International Style, Japanese mid-century posters, psychedelic posters, WPA posters, Cuban posters",
    "Printmaking techniques and printmakers: woodcut, wood engraving, linocut, etching, drypoint, aquatint, mezzotint, lithography, screenprint, risograph, cyanotype, monotype",
    "Japanese art: yamato-e, emaki, Kano and Rimpa schools, nanga, Zen ink, ukiyo-e masters, shin-hanga, sōsaku-hanga, Meiji and Taishō painting",
    "Chinese art: gongbi, xieyi, blue-green landscape, literati shan shui, court painting, Shanghai school, nianhua New Year prints, papercut, Republican-era illustration",
    "Korean, Mongolian, Tibetan (secular) and Central Asian art: minhwa, Joseon court painting, Mongol zurag, Kazakh and Uzbek painting, Central Asian miniature",
    "Persian, Ottoman, Arab and Mughal art: Persian miniature schools, Ottoman miniature and Iznik, Mughal and Deccani painting, Qajar painting, Arab manuscript painting",
    "Indian art beyond Mughal: Rajput (Mewar, Bundi, Kishangarh), Pahari (Kangra, Basohli), Company painting, Kalighat, Bengal School, Madhubani, Gond, Warli, Pattachitra, Tanjore, Kerala murals, Cheriyal scrolls",
    "Southeast Asian art: Balinese Kamasan and Batuan, Javanese wayang imagery, Thai temple murals, Burmese parabaik, Vietnamese lacquer and Dong Ho prints, Filipino and Malaysian modernists",
    "African art traditions and modern African painters: Ethiopian painting, Tingatinga, Ndebele house painting, Kuba textiles, bogolan, Yoruba and Benin imagery, Egyptian and Nubian painting, Congolese popular painting, South African modernists (deceased)",
    "Ancient art as imagery: Egyptian tomb painting, Minoan frescoes, Greek black- and red-figure vase painting, Etruscan, Roman fresco and mosaic, Pompeian styles, Mesopotamian reliefs, Scythian animal style",
    "Pre-Columbian and Indigenous art of the Americas (secular): Maya murals, Aztec codices as imagery, Moche ceramics painting, Andean textiles, Cusco school, Huichol yarn painting, Kuna mola, Northwest Coast formline (as decorative style), Inuit printmaking (deceased artists)",
    "Latin American modern art: Mexican muralism, Mexican printmaking (Taller de Gráfica Popular), Brazilian modernism, Andean indigenism, Caribbean painters, Argentine and Uruguayan modernists (deceased)",
    "Oceanic and Pacific art (secular): Maori kowhaiwhai patterns, Pacific tapa cloth, Papuan bark painting styles, Hawaiian kapa, early Australian and New Zealand painters (non-sacred, deceased)",
    "Decorative crafts as image-making: stained glass, mosaic, tapestry, embroidery, quilt, appliqué, papercut, marquetry, cloisonné enamel, lacquer, batik, ikat, tile painting, ceramic painting, inlay, scrimshaw, painted furniture",
    "Natural history, botanical, scientific and anatomical illustration from the 16th to 20th c.",
    "Architectural drawing, cartography and technical illustration as imagery: Piranesi-style etching, Beaux-Arts rendering, axonometric drawing, blueprint, cutaway, isometric, old maps (pictorial, without lettering)",
    "Historic photography processes and deceased photographers: daguerreotype, albumen, autochrome, pictorialism, Prokudin-Gorsky colour, Kodachrome era, documentary and street photography masters, large-format landscape",
    "Watercolour and drawing traditions: English watercolour school, plein-air watercolour, pen-and-ink, silverpoint, charcoal, pastel, sanguine, gouache sketching (masters and schools)",
    "Mural, fresco and public art traditions worldwide: Renaissance fresco, Mexican mural, Soviet mosaic, WPA murals, Mughal wall painting, Tibetan secular murals, Mexican tile murals",
    "Theatre and costume design, ballet design (Bakst, Goncharova, Benois), stage set painting, puppet and shadow theatre imagery (wayang, karagöz, Chinese shadow puppets)",
    "Modern illustration movements 1940–1990: mid-century modern illustration, UPA-influenced graphics, Push Pin Studios era, Eastern European illustration, Soviet magazine illustration, Pan Am-era travel art (deceased artists)",
    "Contemporary and digital looks (techniques, not people): low-poly 3D, isometric pixel art, papercraft diorama, tilt-shift miniature, claymation still, felt and wool craft, voxel art, cel-shaded 3D, matte painting, risograph zine, flat vector illustration",
    "Material and sculptural imagery: bas-relief in stone or wood, carved wood folk sculpture, terracotta, bronze relief, origami, paper sculpture, clay figurines, toy theatre, tin toys, wax relief, glass beadwork",
    "Women artists across history not already obvious: from Sofonisba Anguissola and Rachel Ruysch to Hilma af Klint, Zinaida Serebriakova, Tarsila do Amaral, Amrita Sher-Gil, Leonora Carrington and many more (deceased)",
    "Lesser-known regional schools of Europe: Catalan Modernisme, Portuguese azulejo painters, Hungarian Nagybánya, Czech and Slovak modernists, Polish Young Poland, Romanian, Bulgarian, Greek, Georgian, Armenian and Balkan painters (deceased)",
]

EXISTING_SYSTEM = SYSTEM.replace("- Give between 40 and 60 entries for the section.",
                                 "- Give exactly one entry per style in the user's list, in the same order; skip only living artists, brands or sacred practices.")


def ask(system, user, tag):
    path = os.path.join(RAW, f"{tag}.json")
    if os.path.exists(path):
        return tag, "cached"
    t = time.monotonic()
    llm = build_llm_provider("opus", CFG)
    for attempt in range(3):
        try:
            text = llm.generate(system, user).strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
            data = json.loads(text)
            assert isinstance(data, list) and data
            json.dump({"request": user, "items": data}, open(path, "w"), ensure_ascii=False, indent=1)
            return tag, f"{len(data)} шт., {time.monotonic() - t:.0f} c"
        except Exception as exc:  # noqa: BLE001
            err = exc
    return tag, f"ОШИБКА: {err}"


def run_sections():
    jobs = [(SYSTEM, f"Section: {s}", f"s{n:02d}") for n, s in enumerate(SECTIONS)]
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for tag, status in pool.map(lambda j: ask(*j), jobs):
            print(tag, status, flush=True)


KINDS = {"artist", "school", "movement", "tradition", "technique"}


def plain(text):
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def norm(name):
    name = plain(re.sub(r"\(.*?\)", "", name)).lower()
    name = re.sub(r"[^a-z0-9а-яё ]+", " ", name)
    return " ".join(name.split())


def slug(name):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", plain(name).lower())).strip("-")[:60]


def short_section(n):
    return re.split(r"[:(]", SECTIONS[n])[0].strip()


def run_existing():
    have = set()
    for f in os.listdir(RAW):
        if f.startswith("s"):
            for it in json.load(open(os.path.join(RAW, f)))["items"]:
                have.add(norm(it["name"]))
    existing = json.load(open(os.path.join(RAW, "existing.json")))
    seen, todo = set(), []
    for e in existing:
        n = norm(e["style"])
        if n in seen or n in have or any(n in h or h in n for h in have if len(h) > 6 and len(n) > 6):
            continue
        seen.add(n)
        todo.append(f"{e['style']}  [context: {e['section']}]")
    print("недостающих из таблиц:", len(todo))
    chunks = [todo[i:i + 45] for i in range(0, len(todo), 45)]
    jobs = [(EXISTING_SYSTEM, "Make catalogue entries for these styles (the bracketed context says which "
             "section of an older table the style came from):\n" + "\n".join(c), f"e{n:02d}")
            for n, c in enumerate(chunks)]
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for tag, status in pool.map(lambda j: ask(*j), jobs):
            print(tag, status, flush=True)


def run_build():
    styles, by_norm, problems = [], {}, []
    files = [f for f in os.listdir(RAW) if re.fullmatch(r"[se]\d+\.json", f)]
    for f in sorted(files, key=lambda f: (f[0] != "s", f)):          # сначала разделы, потом старые таблицы
        items = json.load(open(os.path.join(RAW, f)))["items"]
        for it in items:
            try:
                name = " ".join(str(it["name"]).split())
                features = " ".join(str(it["features"]).split())
                suits = [s for s in it.get("suits") or [] if s in SUITS]
                entry = {
                    "name": name,
                    "kind": it.get("kind") if it.get("kind") in KINDS else "tradition",
                    "medium": " ".join(str(it.get("medium") or "").split()),
                    "region": " ".join(str(it.get("region") or "").split()),
                    "era": " ".join(str(it.get("era") or "").split()),
                    "features": features,
                    "fame": min(max(int(it.get("fame") or 1), 1), 3),
                    "figurative": min(max(int(it.get("figurative") if it.get("figurative") is not None else 2), 0), 2),
                    "text": bool(it.get("text")),
                    "suits": suits,
                    "section": short_section(int(f[1:3])) if f[0] == "s" else "Из прежних таблиц",
                }
                if it.get("note"):
                    entry["note"] = " ".join(str(it["note"]).split())
            except (KeyError, TypeError, ValueError) as exc:
                problems.append(f"{f}: {it!r:.80} — {exc}")
                continue
            words = len(features.split())
            if not name or words < 8 or not suits:
                problems.append(f"{f}: «{name}» — признаков {words} слов, тем {len(suits)}")
                continue
            key = norm(name)
            if key in by_norm:
                first = by_norm[key]
                first["suits"] = [s for s in SUITS if s in set(first["suits"]) | set(suits)]
                first["text"] = first["text"] or entry["text"]
                continue
            by_norm[key] = entry
            styles.append(entry)

    used = set()
    for entry in styles:
        base = slug(entry["name"]) or "style"
        sid, n = base, 2
        while sid in used:
            sid, n = f"{base}-{n}", n + 1
        used.add(sid)
        entry["id"] = sid

    ordered = [{k: e[k] for k in ("id", "name", "kind", "medium", "region", "era", "features", "fame",
                                   "figurative", "text", "suits", "section", "note") if k in e} for e in styles]
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as file:
        json.dump({"generated": datetime.date.today().isoformat(),
                   "source": "Claude Opus 5.5 по разделам мирового искусства + стили прежних таблиц промптов",
                   "count": len(ordered), "styles": ordered}, file, ensure_ascii=False, indent=1)

    print("стилей:", len(ordered), "| отброшено:", len(problems))
    for p in problems[:15]:
        print("  ", p)
    print("темы:", dict(Counter(s for e in ordered for s in e["suits"])))
    print("известность:", dict(Counter(e["fame"] for e in ordered)),
          "изобразительность:", dict(Counter(e["figurative"] for e in ordered)),
          "с надписями:", sum(e["text"] for e in ordered))


if __name__ == "__main__":
    os.makedirs(RAW, exist_ok=True)
    {"sections": run_sections, "existing": run_existing, "build": run_build}[sys.argv[1]]()
