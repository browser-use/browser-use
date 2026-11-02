import { createServer } from 'node:http';

export async function startFixture() {
  const server = createServer((req, res) => {
    if (req.url === '/catalog.csv') {
      res.writeHead(200, {
        'content-type': 'text/csv',
        'content-disposition': 'attachment; filename="catalog.csv"',
      });
      res.end('name,price\nAtlas,29\nOrbit,49\n');
      return;
    }
    if (req.url === '/frame') {
      res.setHeader('content-type', 'text/html; charset=utf-8');
      res.end(
        '<label>Reference <input id="ref"></label><button onclick="document.querySelector(\'#value\').textContent=document.querySelector(\'#ref\').value">Save reference</button><p id="value"></p>',
      );
      return;
    }
    res.setHeader('content-type', 'text/html; charset=utf-8');
    res.end(`<!doctype html><html lang="en"><head><title>Orbital Supply — test fixture</title><style>
      body{font:17px system-ui;background:#f5f6f8;color:#121a2b;max-width:900px;margin:70px auto;padding:24px}h1{font-size:48px;letter-spacing:-2px}button,a,input,select{font:inherit;padding:12px;margin:8px 8px 8px 0}button{background:#235bea;color:white;border:0;border-radius:8px}article{padding:16px;background:white;margin:12px 0;border-radius:12px}.label{color:#65718b;font-size:13px;letter-spacing:2px}#status{font-weight:600;color:#235bea}iframe{background:white;border:1px solid #ddd;width:100%;height:170px}
      </style></head><body><p class="label">BROWSER USE / LOCAL TEST STORE</p><h1>Orbital Supply</h1><p>A real browser. A local fixture. No account, no checkout.</p>
      <form id="search"><label>Search products <input name="query" type="search"></label><button>Search</button></form>
      <section id="products"><article data-price="29"><h2>Atlas</h2><p>Travel charger · $29</p></article><article data-price="49"><h2>Orbit</h2><p>Desktop charger · $49</p></article></section>
      <label>Shipping <select id="shipping" aria-label="Shipping"><option>Standard</option><option>Express</option></select></label>
      <label>Attach notes <input type="file" id="upload"></label>
      <p><button id="save">Save selection</button><a href="/catalog.csv" download>Export catalog</a><a href="/details" target="_blank">Open details</a></p>
      <p id="status" role="status">No selection saved</p><iframe title="Reference" src="/frame"></iframe><div id="shadow"></div>
      <script>
      let saves=0;document.querySelector('#save').onclick=()=>{document.querySelector('#status').textContent='Saved '+(++saves)+' time(s)'};
      document.querySelector('#search').onsubmit=e=>{e.preventDefault();const q=e.target.query.value.toLowerCase();for(const a of document.querySelectorAll('article'))a.hidden=!a.textContent.toLowerCase().includes(q)};
      document.querySelector('#shadow').attachShadow({mode:'open'}).innerHTML='<button>Shadow action</button>';document.querySelector('#shadow').shadowRoot.querySelector('button').onclick=e=>e.target.textContent='Shadow done';
      </script></body></html>`);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    close: () =>
      new Promise((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
      ),
  };
}
