from pathlib import Path
import gzip,hashlib,json,re
root=Path(__file__).resolve().parents[1]
m=json.loads((root/'manifest.json').read_text()); total=0
assert m['schema']==1 and m['scope']=='europe-switzerland' and 1000<=m['count']<=5000000
allowed={'code','product_name','product_name_en','product_name_fr','countries_tags','brands','quantity','product_quantity_unit','nutrition_data_per','last_modified_t','nutriments'}
markets=set(json.loads((root/'markets.json').read_text()))
for p in m['parts']:
 assert re.fullmatch(r'foods-[a-f0-9]{12}-[0-9]{3,4}\.jsonl\.gz',p['file'])
 file=root/p['file']; assert file.stat().st_size==p['bytes'] and hashlib.sha256(file.read_bytes()).hexdigest()==p['sha256']
 rows=0
 with gzip.open(file,'rt',encoding='utf-8') as f:
  for line in f:
   food=json.loads(line); assert set(food)<=allowed and markets.intersection(food['countries_tags'])
   assert re.fullmatch(r'[0-9]{8}|[0-9]{13}|[0-9]{14}',food['code']) and len(line.encode('utf-8'))<=65536
   rows+=1
 assert rows==p['rows']; total+=rows
assert total==m['count']; print('Verified',total,'public food rows; no image or personal fields.')
