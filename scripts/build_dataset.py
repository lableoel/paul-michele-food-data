"""Build attributed data-only Europe/Switzerland packs from the official OFF bulk export.

No product API crawling, images, contributor identities or personal app records.
Standard-library-only; raw source/cache paths must stay outside distributable packs.
"""
import argparse, csv, datetime, gzip, hashlib, json, pathlib, re, sqlite3, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = 'https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz'
HEADERS = {'User-Agent': 'PaulMichele/2.2.0 (dev2@leutrim.ch)', 'Accept-Encoding': 'identity'}

def barcode(raw):
    if not re.fullmatch(r'(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})', raw or '') or not raw.strip('0'): return None
    if sum(int(n) * (3 if i % 2 == 0 else 1) for i, n in enumerate(raw[-2::-1])) % 10 != (-int(raw[-1])) % 10: return None
    code = raw.lstrip('0')
    return code.zfill(8 if len(code) <= 8 else 13 if len(code) <= 13 else 14)

def download(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    info = urllib.request.urlopen(urllib.request.Request(SOURCE, headers=HEADERS, method='HEAD'), timeout=60)
    size, etag = int(info.headers['Content-Length']), info.headers.get('ETag', '')
    stamp = target.with_suffix(target.suffix + '.etag')
    if stamp.exists() and stamp.read_text() != etag: target.unlink(missing_ok=True)
    stamp.write_text(etag)
    offset = target.stat().st_size if target.exists() else 0
    if offset == size: return
    if offset > size: target.unlink(); offset = 0
    headers = {**HEADERS, **({'Range': 'bytes=%d-' % offset, 'If-Range': etag} if offset else {})}
    request = urllib.request.urlopen(urllib.request.Request(SOURCE, headers=headers), timeout=90)
    if offset and request.status != 206: offset = 0
    last = 0
    with target.open('ab' if offset else 'wb') as out:
        while True:
            chunk = request.read(1024 * 1024)
            if not chunk: break
            out.write(chunk); offset += len(chunk)
            if time.monotonic() - last > 15:
                print('Public source download: %.1f%% (%d bytes)' % (offset / size * 100, offset), flush=True); last = time.monotonic()
    if offset != size: raise RuntimeError('Incomplete source download; rerun to resume')

def build(source, output):
    output.mkdir(parents=True, exist_ok=True)
    countries = set(json.loads((ROOT / 'markets.json').read_text(encoding='utf-8')))
    database = output.parent / 'food-dataset-build.sqlite'
    db = sqlite3.connect(database); db.execute('DROP TABLE IF EXISTS products'); db.execute('CREATE TABLE products(code TEXT PRIMARY KEY,data TEXT NOT NULL)')
    csv.field_size_limit(16 * 1024 * 1024)
    examined = accepted = 0
    with gzip.open(source, 'rt', encoding='utf-8-sig', newline='') as file:
        # Some community text fields contain NULs; Python 3.10's CSV parser rejects them.
        reader = csv.DictReader((line.replace('\0', '') for line in file), delimiter='\t')
        if not {'code', 'countries_tags', 'product_name'}.issubset(reader.fieldnames or []): raise RuntimeError('Unsupported OFF CSV schema')
        for row in reader:
            examined += 1
            tags = [x.strip() for x in row.get('countries_tags', '').split(',') if x.strip()]
            if not countries.intersection(tags): continue
            code = barcode(row.get('code', '')); name = row.get('product_name', '').strip()
            if not code or not name: continue
            product = {'code': code, 'product_name': name[:160], 'countries_tags': tags, 'nutriments': {}}
            for field in ['product_name_en', 'product_name_fr', 'brands', 'quantity', 'product_quantity_unit', 'nutrition_data_per']:
                if row.get(field): product[field] = row[field].strip()[:160]
            for field in ['energy-kcal_100g', 'energy-kj_100g', 'energy_100g', 'proteins_100g', 'carbohydrates_100g', 'fat_100g']:
                raw = row.get(field, '').strip()
                if raw:
                    try:
                        value = float(raw)
                        if 0 <= value <= (5000 if field.startswith('energy') else 100): product['nutriments'][field] = value
                    except ValueError: pass
            try: product['last_modified_t'] = max(0, min(4102444800, int(row.get('last_modified_t') or 0)))
            except ValueError: product['last_modified_t'] = 0
            db.execute('INSERT OR REPLACE INTO products VALUES(?,?)', (code, json.dumps(product, separators=(',', ':'), ensure_ascii=False)))
            accepted += 1
            if accepted % 10000 == 0:
                db.commit(); print('Filtered public records: %d accepted / %d examined' % (accepted, examined), flush=True)
    db.commit(); count = db.execute('SELECT COUNT(*) FROM products').fetchone()[0]
    if count < 1000: raise RuntimeError('Unexpectedly small regional snapshot; refusing publication')
    parts, file, rows, raw_bytes, part = [], None, 0, 0, 0
    def close_part():
        if not file: return
        file.close(); path = output / ('foods-%03d.jsonl.gz' % part)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        named = output / ('foods-%s-%03d.jsonl.gz' % (sha[:12], part))
        path.replace(named)
        parts.append({'file': named.name, 'bytes': named.stat().st_size, 'sha256': sha, 'rows': rows})
    for (data,) in db.execute('SELECT data FROM products ORDER BY code'):
        encoded = (data + '\n').encode('utf-8')
        if file is None or raw_bytes + len(encoded) > 16 * 1024 * 1024:
            close_part(); part += 1; rows = raw_bytes = 0
            file = gzip.open(output / ('foods-%03d.jsonl.gz' % part), 'wb', compresslevel=6)
        file.write(encoded); rows += 1; raw_bytes += len(encoded)
    close_part(); db.close()
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    digest = hashlib.sha256(''.join(p['sha256'] for p in parts).encode()).hexdigest()[:12]
    manifest = {'schema': 1, 'scope': 'europe-switzerland', 'version': now[:10] + '-' + digest, 'createdAt': now, 'count': count, 'parts': parts,
                'source': SOURCE, 'license': 'https://opendatacommons.org/licenses/odbl/1-0/', 'attribution': 'Contains information from Open Food Facts, available under the Open Database License (ODbL). Individual contents: Database Contents License. No product images included.'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (output / 'README.txt').write_text(manifest['attribution'] + '\nSource: https://world.openfoodfacts.org/data\nScope: products sold in Switzerland or European markets; source coverage varies. Data can be incomplete or outdated; compare package labels. No images or personal records.\n', encoding='utf-8')
    print(json.dumps({'count': count, 'parts': len(parts), 'compressedBytes': sum(p['bytes'] for p in parts), 'version': manifest['version']}), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--source', type=pathlib.Path, required=True); parser.add_argument('--output', type=pathlib.Path, required=True); parser.add_argument('--download', action='store_true'); args = parser.parse_args()
    if args.download: download(args.source)
    build(args.source, args.output)
