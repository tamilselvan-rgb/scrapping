from bs4 import BeautifulSoup
s=BeautifulSoup(open('hausbau_all.html',encoding='utf-8').read(),'html.parser')
item=next(x for x in s.find_all('div',class_=lambda c: c and 'jet-listing-dynamic-post-' in c) if x.find('h3'))
for e in item.find_all():
 txt=' '.join(e.get_text(' ',strip=True).split())
 if txt and len(txt)<300 and e.name not in ['svg','path','span']:
  print(e.name,' '.join(e.get('class',[])),repr(txt))
