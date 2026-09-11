import re
import pandas as pd

def html_table_to_df(html_str: str) -> pd.DataFrame:
    rows = re.findall(r"<tr>(.*?)</tr>", html_str, re.DOTALL | re.IGNORECASE)
    table_data = []
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        table_data.append([re.sub(r"<[^>]+>", "", c).strip() for c in cells])
    if not table_data:
        return pd.DataFrame()
    header = table_data[0]
    data = table_data[1:]
    return pd.DataFrame(data, columns=header)

html = '<html><body><table><tr><td>Item</td><td>Price</td><td>Discount</td></tr><tr><td>Panadol Extra</td><td>50.00</td><td>20%</td></tr><tr><td>Cataflam 50 mg</td><td>35.00</td><td>15%</td></tr></table></body></html>'
df = html_table_to_df(html)
print(df)
print(df.to_dict(orient="records"))
