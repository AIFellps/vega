// Rosto holográfico da Vega (motor 3D). Tudo local, sem internet: three.js 0.160 em web/libs/three (licença MIT) e o modelo
// web/modelos/rosto.glb, feito a partir do "Human Base Meshes" da Blender Foundation (CC0, domínio público).
// Aceita outro modelo .glb: com as expressões do ARKit (jawOpen, eyeBlink_L...) ele usa todas; sem elas, só mexe a boca se tiver "jawOpen".
// Precisa na página: um elemento #palco (onde o 3D desenha), um #aviso, o importmap do three 0.160 e window.VEGA (config.json).
// Controle: window.rostoVega.mudar("ocioso" | "pensando" | "falando") e window.rostoVega.pulso() a cada palavra falada.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

// ---------------------------------------------------------------- palco
const PW = () => document.getElementById("palco").clientWidth, PH = () => document.getElementById("palco").clientHeight;
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, matchMedia("(pointer: coarse)").matches ? 1.5 : 2));   // no celular, mais leve
renderer.setSize(PW(), PH());
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.95;
const PALCO = document.getElementById("palco");
PALCO.prepend(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x020409);
const CORES = (window.VEGA && window.VEGA.cores) || {};
const COR = { ocioso: new THREE.Color(CORES.espera || "#2ad8ff"), pensando: new THREE.Color(CORES.pensando || "#8a5cff"), falando: new THREE.Color(CORES.falando || "#ff9a3c") };
const camera = new THREE.PerspectiveCamera(32, PW() / PH(), 0.01, 100);
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(PW(), PH()), 0.45, 0.35, 0.22);
composer.addPass(bloom);
composer.addPass(new OutputPass());

const U = {                                         // uniforms compartilhados por tudo
  uTime: { value: 0 }, uScan: { value: 0 }, uAmp: { value: 0 }, uThink: { value: 0 }, uAssemble: { value: 0 },
  uScale: { value: 1 }, uMinY: { value: 0 }, uMaxY: { value: 1 }, uMouth: { value: new THREE.Vector3() },
  uPx: { value: 1 }, uGlitch: { value: 0 }, uGlitchY: { value: 0 },
  uC1: { value: COR.ocioso }, uC2: { value: COR.pensando }, uC3: { value: COR.falando },   // as cores do config.json
};

// ---------------------------------------------------------------- shaders
const MORPH_VERT = `
  #include <beginnormal_vertex>
  #include <morphnormal_vertex>
  #include <begin_vertex>
  #include <morphtarget_vertex>`;

const ONDA = `
  float onda(vec3 p){                                  // pulso âmbar que sai da boca quando fala
    float d = distance(p, uMouth) / uScale;
    return uAmp * exp(-pow(fract(d * 2.6 - uTime * 1.7) - 0.5, 2.0) * 70.0) * exp(-d * 2.2);
  }`;

const UNIF = `uniform float uTime, uScan, uAmp, uThink, uAssemble, uScale, uMinY, uMaxY, uPx, uGlitch, uGlitchY; uniform vec3 uMouth, uC1, uC2, uC3;`;

const casca = new THREE.ShaderMaterial({
  uniforms: U, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  vertexShader: `${UNIF}
    #include <common>
    #include <morphtarget_pars_vertex>
    varying vec3 vPos; varying vec3 vN; varying vec3 vView;
    void main(){
      ${MORPH_VERT}
      vPos = transformed;
      float g = uGlitch * step(abs(transformed.y - uGlitchY), 0.018 * uScale);
      transformed.x += g * 0.05 * uScale;
      vec4 mv = modelViewMatrix * vec4(transformed, 1.0);
      vView = -mv.xyz; vN = normalize(normalMatrix * objectNormal);
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: `${UNIF}
    varying vec3 vPos; varying vec3 vN; varying vec3 vView;
    ${ONDA}
    void main(){
      vec3 n = normalize(vN), v = normalize(vView);
      float fres = pow(1.0 - abs(dot(n, v)), 2.4);
      float h = (vPos.y - uMinY) / (uMaxY - uMinY);
      vec3 base = mix(uC1 * vec3(0.12, 0.12, 0.55), uC1, smoothstep(0.05, 0.85, h));
      base = mix(base, uC2, uThink * 0.6);
      float curvas = (pow(0.5 + 0.5 * sin(vPos.y / uScale * 190.0), 40.0) + pow(0.5 + 0.5 * sin(vPos.x / uScale * 190.0), 40.0)) * 0.22;   // malha fina
      float faixa = exp(-pow((h - uScan) * 16.0, 2.0));
      float w = onda(vPos);
      float fundo = smoothstep(0.0, 0.18, h);                                          // pescoço some no escuro
      vec3 cor = base * (0.02 + fres * 0.65 + curvas * 1.2) + uC1 * faixa * 0.3 + uC3 * w * 0.9;
      float a = clamp(0.03 + fres * 0.7 + curvas * 0.6 + faixa * 0.25 + w * 0.7, 0.0, 0.85) * fundo * uAssemble;
      gl_FragColor = vec4(cor * a, 1.0);
    }`,
});

const pontos = new THREE.ShaderMaterial({
  uniforms: U, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  vertexShader: `${UNIF}
    #include <common>
    #include <morphtarget_pars_vertex>
    attribute vec3 aRand;
    varying float vB; varying vec3 vC;
    ${ONDA}
    void main(){
      ${MORPH_VERT}
      float h = (transformed.y - uMinY) / (uMaxY - uMinY);
      // chegada: cada ponto vem de longe, com atraso próprio
      float t = clamp((uAssemble - aRand.x * 0.55) / 0.45, 0.0, 1.0); t = t * t * (3.0 - 2.0 * t);
      vec3 longe = (aRand - 0.5) * uScale * 7.0 + vec3(0.0, uScale * 1.5, uScale * 1.0);
      vec3 p = mix(longe, transformed, t);
      // pensando: uma parte dos pontos se solta e orbita a cabeça
      float solto = uThink * step(0.9, aRand.y) * (0.5 + 0.5 * sin(uTime * 0.9 + aRand.x * 6.283));
      float ang = uTime * (0.35 + aRand.z * 0.8) + aRand.x * 6.283;
      vec3 orb = vec3(cos(ang), (aRand.z - 0.5) * 1.1, sin(ang)) * uScale * (0.62 + aRand.y * 0.35) + vec3(0.0, (uMinY + uMaxY) * 0.55, 0.0);
      p = mix(p, orb, solto);
      float g = uGlitch * step(abs(transformed.y - uGlitchY), 0.018 * uScale);
      p.x += g * 0.05 * uScale;
      float w = onda(transformed);
      float faixa = exp(-pow((h - uScan) * 16.0, 2.0));
      float pisca = 0.5 + 0.5 * sin(uTime * (0.8 + aRand.y * 3.0) + aRand.z * 40.0);
      float fundo = smoothstep(0.0, 0.22, h);
      vB = (0.07 + 0.16 * pisca * pisca + faixa * 0.6 + w * 1.4 + solto * 0.9) * mix(0.35, 1.0, t) * mix(1.0, fundo, t);
      vC = mix(uC1 * vec3(0.4, 0.4, 1.0), uC1, smoothstep(0.1, 0.9, h));
      vC = mix(vC, uC2, max(solto, uThink * 0.4));
      vC = mix(vC, uC3, clamp(w * 1.4, 0.0, 1.0));
      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      gl_PointSize = uPx * (0.32 + aRand.y * 0.4 + w * 1.0 + faixa * 0.3 + solto * 0.6) / -mv.z;
      gl_Position = projectionMatrix * mv;
      gl_Position.z -= 0.004 * gl_Position.w;                               // um fio à frente da pele: a máscara não engole o ponto
    }`,
  fragmentShader: `
    varying float vB; varying vec3 vC;
    void main(){
      float r = length(gl_PointCoord - 0.5);
      if (r > 0.5) discard;
      gl_FragColor = vec4(vC * vB * smoothstep(0.5, 0.0, r), 1.0);
    }`,
});

// ---------------------------------------------------------------- olhos: íris holográfica pintada no próprio globo ocular
const OLHAR = new THREE.Vector3(0, 0, 1);              // para onde as íris apontam (mundo); segue o mouse
const iris = new THREE.ShaderMaterial({
  uniforms: { uTime: U.uTime, uAmp: U.uAmp, uThink: U.uThink, uAssemble: U.uAssemble, uOlhar: { value: OLHAR }, uCor: { value: COR.ocioso.clone() }, uPisca: { value: 0 } },
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  vertexShader: `varying vec3 vN;
    void main(){ vN = normalize(mat3(modelMatrix) * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `uniform float uTime, uAmp, uThink, uAssemble, uPisca; uniform vec3 uOlhar, uCor; varying vec3 vN;
    void main(){
      vec3 n = normalize(vN), f = normalize(uOlhar);
      float c = dot(n, f);                                           // 1 no centro da pupila, cai para as bordas
      vec3 lado = normalize(cross(f, vec3(0.0, 1.0, 0.0))), cima = cross(lado, f);
      float ang = atan(dot(n, cima), dot(n, lado));
      float giro = uTime * (0.35 + uThink * 1.8);
      float borda = smoothstep(0.86, 0.885, c) * (1.0 - smoothstep(0.885, 0.91, c));          // contorno da íris
      float corpo = smoothstep(0.88, 0.9, c) * (1.0 - smoothstep(0.965, 0.972, c));          // íris
      float raios = 0.35 + 0.65 * pow(0.5 + 0.5 * sin(ang * 28.0), 3.0);
      float tracejado = smoothstep(0.943, 0.948, c) * (1.0 - smoothstep(0.952, 0.957, c)) * step(0.45, fract(ang / 6.2832 * 10.0 + giro));
      float pupila = smoothstep(0.965, 0.972, c) * (1.0 - smoothstep(0.972, 0.979, c));     // anel fino em volta da pupila escura
      float lente = smoothstep(0.996, 0.999, c);                                              // ponto de luz no centro
      float esclera = 0.04 * smoothstep(0.3, 0.86, c);
      float pulso = 1.0 + uAmp * 0.6;
      vec3 cor = uCor * (borda * 1.1 + corpo * raios * 0.45 * pulso + tracejado * 0.9 + pupila * 1.3 + esclera) + vec3(0.85, 0.97, 1.0) * lente * 0.9;
      gl_FragColor = vec4(cor * uAssemble * (1.0 - uPisca * 0.9), 1.0);     // modelo sem pálpebras: a íris apaga ao piscar
    }`,
});

// ---------------------------------------------------------------- o rosto
const cabeca = new THREE.Group();
scene.add(cabeca);
let rosto = null, nuvens = [], dic = {};

new GLTFLoader().setMeshoptDecoder(MeshoptDecoder)
  .load(window.MODELO_3D, (gltf) => {
    const modelo = gltf.scene;
    modelo.updateMatrixWorld(true);
    const caixa = new THREE.Box3().setFromObject(modelo);
    const tam = caixa.getSize(new THREE.Vector3()), centro = caixa.getCenter(new THREE.Vector3());
    modelo.position.sub(centro);
    cabeca.add(modelo);
    modelo.updateMatrixWorld(true);

    // o rosto é a malha com mais expressões (ou, sem nenhuma, a maior); só ele vira holograma
    const malhas = [];
    modelo.traverse((o) => { if (o.isMesh) { malhas.push(o); o.visible = false; } });
    const nota = (o) => Object.keys(o.morphTargetDictionary || {}).length * 1e7 + o.geometry.attributes.position.count;
    rosto = malhas.sort((a, b) => nota(b) - nota(a))[0] || null;
    if (rosto) rosto.visible = true;
    // globos oculares: as duas malhas mais altas além do rosto (se houver dentes, ficam abaixo)
    const outras = [];
    modelo.traverse((o) => { if (o.isMesh && o !== rosto) outras.push([new THREE.Box3().setFromObject(o).getCenter(new THREE.Vector3()).y, o]); });
    outras.sort((x, y) => y[0] - x[0]);
    for (const [, o] of outras.slice(0, 2)) { o.visible = true; o.material = iris; o.renderOrder = 1; }
    if (!rosto) { aviso("não achei as expressões do rosto"); return; }
    dic = rosto.morphTargetDictionary || {};
    if (!rosto.morphTargetInfluences) rosto.morphTargetInfluences = [];
    temPalpebras = dic.eyeBlink_L !== undefined;
    rosto.material = casca;
    // máscara de profundidade: esconde o lado de dentro (boca, órbitas, nuca) para não virar caveira
    const mascara = new THREE.Mesh(rosto.geometry, new THREE.MeshBasicMaterial({ colorWrite: false }));
    mascara.renderOrder = -1;
    rosto.add(mascara);
    const nuvem = amostrar(rosto, PW() < 700 ? 9000 : 16000);
    rosto.add(nuvem);
    nuvens.push({ malha: mascara, nuvem: null }, { malha: null, nuvem });

    // limites em espaço local do rosto
    const pos = rosto.geometry.attributes.position, v = new THREE.Vector3();
    let minY = Infinity, maxY = -Infinity;
    for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i); minY = Math.min(minY, v.y); maxY = Math.max(maxY, v.y); }
    U.uMinY.value = minY; U.uMaxY.value = maxY; U.uScale.value = maxY - minY;
    // boca: os vértices que mais se mexem ao abrir a mandíbula
    const marca = modelo.getObjectByName("boca");                        // o modelo pode marcar a boca com um ponto vazio chamado "boca"
    if (marca) U.uMouth.value.copy(rosto.worldToLocal(marca.getWorldPosition(new THREE.Vector3())));
    else if (dic.jawOpen !== undefined) U.uMouth.value.copy(centroDoMovimento("jawOpen", 0.04));
    else U.uMouth.value.set(0, minY + (maxY - minY) * 0.3, rosto.geometry.boundingBox?.max.z ?? 0);   // sem jawOpen: boca estimada
    const raio = Math.max(tam.x, tam.y) * 0.5;
    enquadrar(raio);
    criarCenario(raio, tam);
    document.getElementById("aviso").style.opacity = 0;
    window.rostoCarregado = true;
  }, undefined, (e) => { console.error(e); aviso("não consegui carregar o modelo 3D: " + (e && (e.message || e.type) || "erro")); });

// pontos espalhados por área sobre os triângulos; cada expressão usada é interpolada junto, então os pontos mexem com o rosto
const comp = (a, i, e) => (e === 0 ? a.getX(i) : e === 1 ? a.getY(i) : a.getZ(i));     // getComponent só existe no three mais novo
const USADAS = ["jawOpen", "eyeBlink_L", "eyeBlink_R", "mouthFunnel", "browInnerUp", "eyeSquint_L", "eyeSquint_R", "mouthSmile_L", "mouthSmile_R"];
function amostrar(malha, n) {
  const g = malha.geometry, pos = g.attributes.position, nor = g.attributes.normal, idx = g.index;
  const tris = (idx ? idx.count : pos.count) / 3, vert = (t, k) => (idx ? idx.getX(t * 3 + k) : t * 3 + k);
  const A = new THREE.Vector3(), B = new THREE.Vector3(), C = new THREE.Vector3(), acum = new Float32Array(tris);
  let total = 0;
  for (let t = 0; t < tris; t++) {
    A.fromBufferAttribute(pos, vert(t, 0)); B.fromBufferAttribute(pos, vert(t, 1)); C.fromBufferAttribute(pos, vert(t, 2));
    total += B.sub(A).cross(C.sub(A)).length() * 0.5; acum[t] = total;
  }
  const usadas = USADAS.filter((u) => dic[u] !== undefined);
  const deltas = usadas.map((u) => g.morphAttributes.position[dic[u]]);
  const P = new Float32Array(n * 3), N = new Float32Array(n * 3), R = new Float32Array(n * 3), M = usadas.map(() => new Float32Array(n * 3));
  for (let i = 0; i < n; i++) {
    let lo = 0, hi = tris - 1; const alvo = Math.random() * total;
    while (lo < hi) { const m = (lo + hi) >> 1; if (acum[m] < alvo) lo = m + 1; else hi = m; }
    const r1 = Math.sqrt(Math.random()), r2 = Math.random(), w = [1 - r1, r1 * (1 - r2), r1 * r2], vs = [vert(lo, 0), vert(lo, 1), vert(lo, 2)];
    for (let e = 0; e < 3; e++) {
      for (let k = 0; k < 3; k++) {
        P[i * 3 + e] += w[k] * comp(pos, vs[k], e);
        N[i * 3 + e] += w[k] * comp(nor, vs[k], e);
        for (let d = 0; d < deltas.length; d++) M[d][i * 3 + e] += w[k] * comp(deltas[d], vs[k], e);
      }
      R[i * 3 + e] = Math.random();
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(P, 3));
  geo.setAttribute("normal", new THREE.BufferAttribute(N, 3));
  geo.setAttribute("aRand", new THREE.BufferAttribute(R, 3));
  geo.morphAttributes.position = M.map((m) => new THREE.BufferAttribute(m, 3));
  geo.morphTargetsRelative = true;
  const nuvem = new THREE.Points(geo, pontos);
  nuvem.frustumCulled = false;
  nuvem.userData.usadas = usadas;
  nuvem.updateMorphTargets();
  return nuvem;
}

function centroDoMovimento(nome, fatia) {
  const i = dic[nome], base = rosto.geometry.attributes.position, delta = rosto.geometry.morphAttributes.position[i];
  const lista = [];
  for (let k = 0; k < base.count; k++) lista.push([Math.hypot(delta.getX(k), delta.getY(k), delta.getZ(k)), k]);
  lista.sort((a, b) => b[0] - a[0]);
  const top = lista.slice(0, Math.max(8, Math.floor(base.count * fatia))), c = new THREE.Vector3(), v = new THREE.Vector3();
  for (const [, k] of top) c.add(v.fromBufferAttribute(base, k));
  return c.divideScalar(top.length);
}

function aviso(t) { const a = document.getElementById("aviso"); a.textContent = t; a.style.opacity = 1; }

// ---------------------------------------------------------------- cenário: anéis, projetor, poeira
const extras = [];
function criarCenario(raio, tam) {
  // anéis de dados em volta da cabeça
  for (const [r, incl, vel, n] of [[1.25, 0.32, 0.12, 900], [1.45, -0.2, -0.07, 1300], [1.1, 1.35, 0.05, 500]]) {
    const g = new THREE.BufferGeometry(), p = new Float32Array(n * 3), a = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const ang = (i / n) * Math.PI * 2, falha = Math.sin(ang * 7) > 0.65 ? 0 : 1;   // anel com lacunas, parece telemetria
      p.set([Math.cos(ang) * raio * r, (Math.random() - 0.5) * raio * 0.015, Math.sin(ang) * raio * r], i * 3);
      a.set([Math.random(), Math.random() * falha, Math.random()], i * 3);
    }
    g.setAttribute("position", new THREE.BufferAttribute(p, 3)); g.setAttribute("aRand", new THREE.BufferAttribute(a, 3));
    const m = new THREE.ShaderMaterial({
      uniforms: { ...U, uCor: { value: COR.ocioso.clone().lerp(new THREE.Color(1, 1, 1), 0.3) } }, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      vertexShader: `uniform float uTime, uPx, uThink; attribute vec3 aRand; varying float vB;
        void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vB = aRand.y * (0.25 + 0.6 * step(0.985, fract(aRand.x * 13.0 + uTime * (0.2 + uThink * 1.2))));
          gl_PointSize = uPx * 0.7 / -mv.z; gl_Position = projectionMatrix * mv; }`,
      fragmentShader: `uniform vec3 uCor; varying float vB; void main(){ float r = length(gl_PointCoord - 0.5); if (r > 0.5) discard; gl_FragColor = vec4(uCor * vB, 1.0); }`,
    });
    const anel = new THREE.Points(g, m);
    anel.rotation.x = incl; anel.position.y = raio * 0.08;
    scene.add(anel); extras.push({ o: anel, vel });
  }
  // poeira de dados no ar
  const n = 420, g = new THREE.BufferGeometry(), p = new Float32Array(n * 3), a = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { p.set([(Math.random() - 0.5) * raio * 8, (Math.random() - 0.5) * raio * 5, (Math.random() - 0.5) * raio * 5], i * 3); a.set([Math.random(), Math.random(), Math.random()], i * 3); }
  g.setAttribute("position", new THREE.BufferAttribute(p, 3)); g.setAttribute("aRand", new THREE.BufferAttribute(a, 3));
  const poeira = new THREE.Points(g, new THREE.ShaderMaterial({
    uniforms: { ...U, uAlt: { value: raio * 5 } }, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `uniform float uTime, uPx, uAlt; attribute vec3 aRand; varying float vB;
      void main(){ vec3 p = position; p.y = mod(p.y + uTime * uAlt * 0.01 * (0.3 + aRand.x) + uAlt * 0.5, uAlt) - uAlt * 0.5;
        vec4 mv = modelViewMatrix * vec4(p, 1.0); vB = 0.05 + 0.12 * aRand.y;
        gl_PointSize = uPx * (0.3 + aRand.z * 0.6) / -mv.z; gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `uniform vec3 uC1; varying float vB; void main(){ float r = length(gl_PointCoord - 0.5); if (r > 0.5) discard; gl_FragColor = vec4(mix(uC1, vec3(1.0), 0.3) * vB * (1.0 - r * 2.0), 1.0); }`,
  }));
  scene.add(poeira);
}

let raioCena = 1;
// espaço livre acima do chat (o palco ocupa a tela toda, para o fundo não mudar de cor embaixo do vidro)
const LIVRE = () => { const c = document.getElementById("chat"); return c ? Math.max(220, PH() - c.offsetHeight - 40) : PH(); };
function enquadrar(raio) {
  raioCena = raio;
  const livre = LIVRE(), tg = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const porAltura = (raio * 0.9) / (tg * (livre / PH()));                // a cabeça enche a faixa livre (os anéis podem sair da tela)
  const porLargura = (raio * 0.82) / (tg * camera.aspect);                // tela estreita (celular): o rosto quase encosta nas laterais
  camera.position.set(0, raio * 0.05, Math.max(porAltura, porLargura));
  camera.lookAt(0, 0, 0);
  camera.setViewOffset(PW(), PH(), 0, (PH() - livre) / 2, PW(), PH());   // sobe a imagem para o meio da faixa livre
  ajustarPx();
}
function ajustarPx() { U.uPx.value = renderer.getPixelRatio() * PH() * 0.0016 * camera.position.z; }

// ---------------------------------------------------------------- estado e voz (quem manda é a página)
let estado = "ocioso", ampAlvo = 0, falaSimulada = 0, pulsoExterno = 0;
function mudar(e) { estado = e; }
// a página chama pulso() a cada palavra falada; sem palavras chegando, as sílabas são simuladas enquanto fala
function pulso(forca = 1) { pulsoExterno = Math.max(pulsoExterno, forca); }
window.rostoVega = { mudar, pulso, estado: () => estado, reenquadrar: () => rosto && enquadrar(raioCena) };

function volume() {
  if (estado !== "falando") return 0;
  pulsoExterno = Math.max(0, pulsoExterno - 1 / 20);
  falaSimulada -= 1 / 60;
  if (falaSimulada <= 0) { ampAlvo = Math.random() < 0.16 ? 0 : 0.3 + Math.random() * 0.6; falaSimulada = 0.07 + Math.random() * 0.12; }
  return Math.min(1, ampAlvo * (0.75 + pulsoExterno * 0.5));
}

// ---------------------------------------------------------------- expressões
const mouse = new THREE.Vector2();
addEventListener("pointermove", (e) => { if (e.pointerType === "mouse") mouse.set(e.clientX / innerWidth - 0.5, e.clientY / innerHeight - 0.5); });   // no celular o dedo não vira a cabeça
let piscar = 2.5, piscando = 0, amp = 0, glitch = 0, proxGlitch = 4, temPalpebras = false;
function expr(nome, v) { const i = dic[nome]; if (i !== undefined) rosto.morphTargetInfluences[i] = v; }

const relogio = new THREE.Clock();
function quadro() {
  requestAnimationFrame(quadro);
  const dt = Math.min(relogio.getDelta(), 0.05), t = relogio.elapsedTime;
  U.uTime.value = t;
  U.uAssemble.value = Math.min(1, U.uAssemble.value + dt * (rosto ? 0.32 : 0));
  U.uThink.value += ((estado === "pensando" ? 1 : 0) - U.uThink.value) * dt * 2.5;
  amp += (volume() - amp) * Math.min(1, dt * 18);
  U.uAmp.value += ((estado === "falando" ? 0.25 + amp : 0) - U.uAmp.value) * dt * 6;
  U.uScan.value = ((t * (estado === "pensando" ? 0.55 : 0.12)) % 1.4) - 0.2;

  // falha holográfica de vez em quando (mais frequente pensando)
  proxGlitch -= dt;
  if (proxGlitch <= 0) { glitch = 1; U.uGlitchY.value = THREE.MathUtils.lerp(U.uMinY.value, U.uMaxY.value, Math.random()); proxGlitch = (estado === "pensando" ? 0.6 : 3) + Math.random() * 4; }
  glitch = Math.max(0, glitch - dt * 9); U.uGlitch.value = glitch * (Math.random() > 0.5 ? 1 : -1);

  if (rosto) {
    piscar -= dt;
    if (piscar <= 0) { piscando = 1; piscar = 2 + Math.random() * 4; }
    piscando = Math.max(0, piscando - dt * 7);
    const pis = Math.sin(piscando * Math.PI);
    expr("eyeBlink_L", pis); expr("eyeBlink_R", pis);
    if (!temPalpebras) iris.uniforms.uPisca.value = pis;
    expr("jawOpen", amp * 0.55);
    expr("mouthFunnel", estado === "falando" ? amp * 0.25 * (0.5 + 0.5 * Math.sin(t * 9)) : 0);
    expr("mouthClose", 0);
    expr("browInnerUp", U.uThink.value * 0.45 + amp * 0.1);
    expr("eyeSquint_L", U.uThink.value * 0.25); expr("eyeSquint_R", U.uThink.value * 0.25);
    expr("mouthSmile_L", estado === "ocioso" ? 0.08 : 0); expr("mouthSmile_R", estado === "ocioso" ? 0.08 : 0);
    for (const { malha, nuvem } of nuvens) {
      if (malha) malha.morphTargetInfluences = rosto.morphTargetInfluences;
      if (nuvem) nuvem.userData.usadas.forEach((u, k) => nuvem.morphTargetInfluences[k] = rosto.morphTargetInfluences[dic[u]]);
    }
    // as íris olham para o mouse (mais rápido que a cabeça) e, pensando, desviam para cima
    const gx = mouse.x * 0.55, gy = -mouse.y * 0.4 + U.uThink.value * 0.25;
    OLHAR.lerp(new THREE.Vector3(gx, gy, 1).normalize().applyQuaternion(cabeca.quaternion), Math.min(1, dt * 8));
    iris.uniforms.uCor.value.lerp(COR[estado] || COR.ocioso, Math.min(1, dt * 4));
    // a cabeça acompanha o mouse, respira e, pensando, olha um pouco para cima
    const alvoY = mouse.x * 0.45 + Math.sin(t * 0.3) * 0.06, alvoX = mouse.y * 0.25 - U.uThink.value * 0.12 + Math.sin(t * 0.47) * 0.03;
    cabeca.rotation.y += (alvoY - cabeca.rotation.y) * dt * 2;
    cabeca.rotation.x += (alvoX - cabeca.rotation.x) * dt * 2;
    cabeca.position.y = Math.sin(t * 0.8) * raioCena * 0.012;
  }
  for (const { o, vel } of extras) o.rotation.y += vel * dt * (1 + U.uThink.value * 3);
  bloom.strength = 0.42 + U.uAmp.value * 0.2;
  composer.render();
}
quadro();

const observador = new ResizeObserver(() => {
  camera.aspect = PW() / PH(); camera.updateProjectionMatrix();
  renderer.setSize(PW(), PH()); composer.setSize(PW(), PH());
  if (rosto) enquadrar(raioCena); else ajustarPx();
});
for (const el of [document.getElementById("palco"), document.getElementById("chat")]) if (el) observador.observe(el);
