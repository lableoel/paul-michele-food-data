"""Pack the verified regional source into a portable, pre-indexed SQLite catalogue.

Only public OFF facts. Fixed-key arrays and independently compressed blocks avoid
duplicating JSON keys and names. The contentless FTS4 index stores tokens once.
Android/iOS install the verified snapshot instead of indexing millions of rows.
"""
import argparse, datetime, gzip, hashlib, json, pathlib, sqlite3, time, zlib

FIELDS = ['product_name','product_name_en','product_name_fr','brands','quantity','product_quantity_unit','countries_tags','nutriments','last_modified_t','nutrition_data_per']
SCHEMA = """
PRAGMA page_size=4096;
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
PRAGMA application_id=1347241551;
PRAGMA user_version=2;
CREATE TABLE products(code INTEGER PRIMARY KEY,block INTEGER NOT NULL,slot INTEGER NOT NULL);
CREATE TABLE blocks(id INTEGER PRIMARY KEY,data BLOB NOT NULL);
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
CREATE VIRTUAL TABLE product_search USING fts4(terms,content='',matchinfo=fts3,tokenize=unicode61);
"""

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def build(source, output, limit=None):
    output.mkdir(parents=True,exist_ok=True)
    target=output/'catalog.sqlite'
    if target.exists(): raise FileExistsError(target)
    src=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)
    db=sqlite3.connect(target);db.executescript(SCHEMA)
    db.execute('PRAGMA cache_size=-65536'); db.execute('PRAGMA temp_store=MEMORY')
    started=time.monotonic();count=0;block_id=0;batch=[];batch_bytes=0
    def flush():
        nonlocal block_id,batch,batch_bytes
        if not batch:return
        block_id+=1
        payload=json.dumps([row[1] for row in batch],separators=(',',':'),ensure_ascii=False).encode()
        db.execute('INSERT INTO blocks VALUES(?,?)',(block_id,zlib.compress(payload,9)))
        db.executemany('INSERT INTO products VALUES(?,?,?)',[(row[0],block_id,i) for i,row in enumerate(batch)])
        db.executemany('INSERT INTO product_search(rowid,terms) VALUES(?,?)',[(row[0],row[2]) for row in batch])
        batch=[];batch_bytes=0
    for code,raw in src.execute('SELECT code,data FROM products ORDER BY CAST(code AS INTEGER)'+(' LIMIT '+str(limit) if limit else '')):
        product=json.loads(raw)
        values=[product.get(field) for field in FIELDS]
        while values and values[-1] is None: values.pop()
        size=len(json.dumps(values,ensure_ascii=False).encode())
        if batch and (len(batch)>=128 or batch_bytes+size>65536):flush()
        terms=' '.join(str(product.get(k,'')) for k in ['product_name','product_name_en','product_name_fr','brands'])
        batch.append((int(code),values,terms));batch_bytes+=size;count+=1
        if count%100000==0:
            flush();db.commit();print(json.dumps({'rows':count,'seconds':round(time.monotonic()-started,1)}),flush=True)
    flush();db.commit();src.close()
    db.execute("INSERT INTO product_search(product_search) VALUES('optimize')");db.commit()
    now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    metadata={'scope':'europe-switzerland','count':str(count),'fields':json.dumps(FIELDS,separators=(',',':')),'format':'zlib-json-array-v2'}
    db.executemany('INSERT INTO metadata VALUES(?,?)',metadata.items());db.commit()
    db.execute('VACUUM');db.execute('PRAGMA journal_mode=DELETE');db.close()
    sha=digest(target);parts=[]
    with target.open('rb') as stream:
        while data:=stream.read(4*1024*1024):
            packed=gzip.compress(data,compresslevel=9,mtime=0);h=hashlib.sha256(packed).hexdigest();name='catalog-'+h[:16]+'.sqlite.gz'
            (output/name).write_bytes(packed);parts.append({'file':name,'bytes':len(packed),'sha256':h,'expandedBytes':len(data),'expandedSha256':hashlib.sha256(data).hexdigest()})
    manifest={'schema':2,'scope':'europe-switzerland','version':now[:10]+'-'+sha[:12],'createdAt':now,'count':count,'format':'sqlite-blocks-v2','databaseBytes':target.stat().st_size,'databaseSha256':sha,'parts':parts,'source':'https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz','license':'https://opendatacommons.org/licenses/odbl/1-0/','attribution':'Contains information from Open Food Facts, under ODbL. Individual contents: DbCL. No images or personal records.'}
    (output/'manifest-v2.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'rows':count,'databaseBytes':target.stat().st_size,'downloadBytes':sum(p['bytes'] for p in parts),'parts':len(parts),'seconds':round(time.monotonic()-started,1)}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=pathlib.Path,required=True);parser.add_argument('--output',type=pathlib.Path,required=True);parser.add_argument('--limit',type=int);args=parser.parse_args()
    build(args.source,args.output,args.limit)
