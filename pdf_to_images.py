import fitz, os
pdf_path = r'C:\Users\Siddhant Gupta\Documents\ShiaanX\Files for one time reference\toopath ai CAPP Screenshots.pdf'
out_dir = r'C:\Users\Siddhant Gupta\Documents\ShiaanX\Files for one time reference\pdf_pages'
os.makedirs(out_dir, exist_ok=True)
doc = fitz.open(pdf_path)
print(f'Total pages: {len(doc)}')
for i, page in enumerate(doc):
    mat = fitz.Matrix(2, 2)
    pix = page.get_pixmap(matrix=mat)
    pix.save(os.path.join(out_dir, f'page_{i+1:02d}.png'))
    print(f'Saved page {i+1}')
print('Done')
