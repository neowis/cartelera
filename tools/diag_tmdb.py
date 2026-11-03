"""Diagnóstico: muestra qué devuelve TMDB para películas que no encuentran cartel. Uso: python3 -I tools/diag_tmdb.py"""
import importlib.util, json, os, sys
sys.argv = ["x", os.environ.get("RUNNER_TEMP", "/tmp") + "/diag"]
spec = importlib.util.spec_from_file_location("s", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scraper.py"))
s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)
print("Clave TMDB presente:", bool(os.environ.get("TMDB_API_KEY") or os.environ.get("TMDB_TOKEN")))
casos = [("El amor solfeando", None, 1930, "Robert Florey"), ("La mujer y el pelele", None, 1929, "Jacques de Baroncelli"),
         ("No soy yo", None, 2024, "Leos Carax"), ("Orange Flavor Wedding", None, 2026, "Christophe Honoré"),
         ("No quiero volver a casa", None, 2000, "Albertina Carri"), ("Fin de jornada", None, 1939, "Julien Duvivier"),
         ("La mujer fantasma", None, 1947, "Roy del Ruth"), ("El cameraman", None, 1928, "Edward Sedgwick"),
         ("Romería", None, 2025, "Carla Simón"), ("Medias hermanas", None, 2025, "Yoel Morales"), ("Your name", None, None, None)]
for t, alt, y, d in casos:
    print(f"\n=== {t} ({y}) dir={d}")
    for lang in ("es-ES", "en-US"):
        try:
            q = {"query": t, "language": lang}
            if y: q["year"] = y
            res = s._tmdb_get("search/movie", q).get("results", [])
            print(f"  [{lang} con año] {len(res)} resultados:", [(m.get('title'), m.get('original_title'), m.get('release_date'), bool(m.get('poster_path'))) for m in res[:4]])
            if y:
                res2 = s._tmdb_get("search/movie", {"query": t, "language": lang}).get("results", [])
                print(f"  [{lang} sin año] {len(res2)}:", [(m.get('title'), m.get('release_date')) for m in res2[:4]])
        except Exception as e:
            print("  ERROR", lang, type(e).__name__, e)
    try: print("  -> tmdb_find:", (lambda m: (m or {}).get("title"))(s.tmdb_find(t, alt, y, need_poster=True, director=d)))
    except Exception as e: print("  -> tmdb_find ERROR", e)
