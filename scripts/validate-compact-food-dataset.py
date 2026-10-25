"""Validate public compact packs, optionally comparing every fact with the source."""
import argparse, gzip, hashlib, json, pathlib, re, sqlite3, zlib
FIELDS=['product_name','product_name_en','product_name_fr','brands','quantity','product_quantity_unit','countries_tags','nutriments','last_modified_t','nutrition_data_per']

def validate(folder, source=None):
    manifest=json.loads((folder/'manifest-v2.json').read_text(encoding='utf-8'))
    assert manifest['schema']==2 and manifest['scope']=='europe-switzerland' and manifest['format']=='sqlite-blocks-v2'
    assert 1000<=manifest['count']<=5000000 and 4096<=manifest['databaseBytes']<=512*1024*1024
    assert 1<=len(manifest['parts'])<=128
    hasher=hashlib.sha256();expanded=0;download=0
    for i,part in enumerate(manifest['parts']):
        assert part['file']=='catalog-'+part['sha256'][:16]+'.sqlite.gz'
        packed=(folder/part['file']).read_bytes();assert len(packed)==part['bytes']<=5*1024*1024
        assert hashlib.sha256(packed).hexdigest()==part['sha256']
        raw=gzip.decompress(packed);assert len(raw)==part['expandedBytes']<=4*1024*1024
        assert i==len(manifest['parts'])-1 or len(raw)==4*1024*1024
        assert hashlib.sha256(raw).hexdigest()==part['expandedSha256']
        hasher.update(raw);expanded+=len(raw);download+=len(packed)
    assert expanded==manifest['databaseBytes'] and hasher.hexdigest()==manifest['databaseSha256'] and download<=256*1024*1024
    # Public validation-only CI uses a temporary assembly; never commits SQLite/source files.
    database=folder/'catalog.sqlite';temporary=not database.exists()
    if temporary:
        with database.open('wb') as output:
            for part in manifest['parts']:output.write(gzip.decompress((folder/part['file']).read_bytes()))
    try:
        db=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
        assert db.execute('PRAGMA application_id').fetchone()[0]==1347241551
        assert db.execute('PRAGMA user_version').fetchone()[0]==2
        schema=db.execute("SELECT sql FROM sqlite_master WHERE name='product_search'").fetchone()[0]
        assert re.sub(r'\s+','',schema.lower())=="createvirtualtableproduct_searchusingfts4(terms,content='',matchinfo=fts3,tokenize=unicode61)"
        # SQLite bug fixed upstream ca8de9a304: contentless FTS4 has no source text
        # to compare. Retain every physical-page check and reject ALL other errors.
        results=[row[0] for row in db.execute('PRAGMA quick_check')]
        assert results and all(x in ('ok','unable to validate the inverted index for FTS4 table main.product_search: SQL logic error') for x in results),results
        metadata=dict(db.execute('SELECT key,value FROM metadata'));fields=json.loads(metadata['fields']);assert fields==FIELDS
        markets_file=folder/'markets.json'
        if markets_file.exists():markets=set(json.loads(markets_file.read_text(encoding='utf-8')))
        else:
            text=(pathlib.Path(__file__).resolve().parents[1]/'app/src/main/assets/www/food-products.js').read_text(encoding='utf-8')
            markets={'en:'+x for x in re.search(r"EUROPE_MARKETS=Object.freeze\(\('([^']+)'\)",text)[1].split()}
        assert metadata['scope']==manifest['scope'] and metadata['format']=='zlib-json-array-v2' and int(metadata['count'])==manifest['count']
        assert db.execute('SELECT COUNT(*) FROM products').fetchone()[0]==manifest['count']
        assert not db.execute("SELECT name FROM sqlite_master WHERE type IN ('trigger','view')").fetchall()
        src=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) if source else None
        expected=iter(src.execute('SELECT CAST(code AS INTEGER),data FROM products ORDER BY CAST(code AS INTEGER)')) if src else None
        products=iter(db.execute('SELECT code,block,slot FROM products ORDER BY code'));count=0
        for block,packed in db.execute('SELECT id,data FROM blocks ORDER BY id'):
            assert len(packed)<=256*1024
            raw=zlib.decompress(packed);assert len(raw)<=256*1024
            rows=json.loads(raw);assert 1<=len(rows)<=128
            for slot,row in enumerate(rows):
                code,actual_block,actual_slot=next(products);assert (actual_block,actual_slot)==(block,slot)
                digits=str(code);canonical=digits.zfill(8 if len(digits)<=8 else 13 if len(digits)<=13 else 14)
                product={'code':canonical,**{field:value for field,value in zip(fields,row) if value is not None}}
                assert len(row)<=len(fields) and set(product).issubset(set(fields)|{'code'}) and isinstance(product['countries_tags'],list)
                assert markets.intersection(product['countries_tags']) and isinstance(product['product_name'],str) and product['product_name'].strip()
                assert set(product['nutriments']).issubset({'energy-kcal_100g','energy-kj_100g','energy_100g','proteins_100g','carbohydrates_100g','fat_100g'})
                if expected:
                    expected_code,expected_json=next(expected);assert code==expected_code
                    assert product==json.loads(expected_json),canonical+' changed public facts'
                count+=1
        assert count==manifest['count'] and next(products,None) is None
        if expected:assert next(expected,None) is None;src.close()
        for term in ['"milk*"','"lait*"','"coffee*"','"cafe*"','"migros*"']:
            db.execute('SELECT rowid FROM product_search WHERE product_search MATCH ? LIMIT 30',(term,)).fetchall()
        db.close()
    finally:
        if temporary:database.unlink(missing_ok=True)
    result={'rows':count,'databaseBytes':expanded,'downloadBytes':download,'parts':len(manifest['parts']),'allFactsCompared':bool(source),'valid':True}
    print(json.dumps(result),flush=True);return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=pathlib.Path,default=pathlib.Path('.'));parser.add_argument('--source',type=pathlib.Path);args=parser.parse_args();validate(args.folder,args.source)
