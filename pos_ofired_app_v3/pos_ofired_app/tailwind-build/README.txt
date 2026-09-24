CÓMO REGENERAR EL CSS (solo si agregas clases nuevas de Tailwind)
====================================================================

Esta app ya NO usa Tailwind por CDN (el script que compilaba CSS en
vivo en el navegador, y que hacía que la app se sintiera pesada). En
su lugar, usa un archivo ya compilado:

    static/css/tailwind.built.css

Ese archivo se generó UNA SOLA VEZ a partir de los mismos colores,
tipografías y animaciones que antes vivían en el <script> de
tailwind.config dentro de templates/index.html.

¿Cuándo hace falta regenerarlo?
Solo si en el futuro agregas al HTML (templates/index.html) o al
JavaScript (static/js/pos.js) alguna clase de Tailwind que no se
haya usado antes en el proyecto. Mientras solo reutilices las clases
que ya existen, no hace falta tocar nada.

Cómo regenerarlo (requiere tener Node.js instalado):

    cd tailwind-build
    npm install -D tailwindcss@3
    npx tailwindcss -i ./input.css -o ../static/css/tailwind.built.css --minify

(El archivo tailwind.config.js de esta carpeta ya apunta a
../templates y ../static/js para detectar las clases usadas).

También puedes simplemente pedirle a Claude que lo regenere por ti.
