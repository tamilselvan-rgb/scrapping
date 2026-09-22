from bs4 import BeautifulSoup
s=BeautifulSoup(open('hausbau_probe.html',encoding='utf-8').read(),'html.parser')
for x in s.find_all('script',src=True): print(x['src'])
