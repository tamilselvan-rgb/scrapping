from bs4 import BeautifulSoup
s=BeautifulSoup(open('hausbau_all.html',encoding='utf-8').read(),'html.parser')
items=[x for x in s.find_all('div',class_=lambda c: c and 'jet-listing-grid__item' in c) if x.find('h3')]
print(len(items))
for item in items[:2]:
 print('---',item.get('class'))
 for el in item.find_all(['h3','p','a','div']):
  txt=' '.join(el.get_text(' ',strip=True).split())
  if txt and (el.name in ['h3','p'] or (el.name=='a' and el.get('href','').startswith(('http','mailto:','tel:')))):
   print(el.name,repr(txt[:300]),el.get('href'))
