from bs4 import BeautifulSoup
s=BeautifulSoup(open('hausbau_probe.html',encoding='utf-8').read(),'html.parser')
for x in s.find_all('script'):
 u=x.get('src') or x.get('data-rocket-src')
 if u: print(u)
