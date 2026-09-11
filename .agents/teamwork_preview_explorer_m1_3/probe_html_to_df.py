from io import StringIO
import pandas as pd

html = '<html><body><table><tr><td>Item</td><td>Price</td><td>Discount</td></tr><tr><td>Panadol Extra</td><td>50.00</td><td>20%</td></tr><tr><td>Cataflam 50 mg</td><td>35.00</td><td>15%</td></tr></table></body></html>'
df = pd.read_html(StringIO(html))[0]
print("DataFrame from HTML table:")
print(df)
print("\nColumns:", df.columns.tolist())
