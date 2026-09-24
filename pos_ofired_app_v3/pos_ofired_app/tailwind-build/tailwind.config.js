/** Config usado SOLO para generar un archivo CSS estático (build),
 * replicando exactamente el theme.extend que antes vivía inline en
 * templates/index.html dentro de <script>tailwind.config = {...}</script>.
 * Esto permite eliminar el script de Tailwind vía CDN (que compila CSS
 * en el navegador cada vez que se abre la app) y servir en su lugar un
 * archivo .css ya compilado y minificado: arranque instantáneo, cero
 * trabajo de CSS-in-JS en tiempo real, y la app funciona sin internet.
 */
module.exports = {
  content: [
    "../templates/**/*.html",
    "../static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        cream:  '#FBF8F3',
        paper:  '#F3ECDF',
        ink:    '#3D352B',
        muted:  '#92867A',
        line:   '#E9DFD0',
        primary: { DEFAULT: '#B6651D', dark: '#8F4F16', light: '#D98A3D', soft: '#FBEEDD' },
        sage:    { DEFAULT: '#3F7857', dark: '#2F5C42', soft: '#E7F1EB' },
        danger:  { DEFAULT: '#C0392B', dark: '#982E22', soft: '#FBEAE7' },
        logindark: '#2A3441',
        logininput: '#374253',
      },
      fontFamily: {
        display: ['"Plus Jakarta Sans"', 'sans-serif'],
        sans: ['"Inter"', 'sans-serif'],
      },
      boxShadow: {
        glass: '0 8px 32px 0 rgba(0, 0, 0, 0.2)',
        glassHover: '0 12px 40px 0 rgba(182, 101, 29, 0.12)',
        innerSoft: 'inset 0 2px 4px 0 rgba(255, 255, 255, 0.5)',
        loginCard: '0 20px 50px -10px rgba(0, 0, 0, 0.3)',
        soft: '0 2px 8px 0 rgba(61, 53, 43, 0.08)',
      },
      animation: {
        'blob': 'blob 25s infinite',
        'fadeInUp': 'fadeInUp 0.4s ease-out forwards',
        'zoomIn': 'zoomIn 0.3s ease-out forwards',
      },
      keyframes: {
        blob: {
          '0%': { transform: 'translate(0px, 0px) scale(1)' },
          '33%': { transform: 'translate(20px, -30px) scale(1.1)' },
          '66%': { transform: 'translate(-15px, 15px) scale(0.9)' },
          '100%': { transform: 'translate(0px, 0px) scale(1)' },
        },
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        zoomIn: {
          '0%': { opacity: '0', transform: 'scale(0.9)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        }
      }
    }
  },
  plugins: [],
}
