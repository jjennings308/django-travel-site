/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    // Theme app templates
    '../templates/**/*.html',
    // Site-level templates
    '../../templates/**/*.html',
    // All app templates
    '../../**/templates/**/*.html',
  ],
  theme: {
    extend: {
      colors: {
        // Earth-tone brand colors
        earth: {
          clay: '#7A4E2D',        // Primary brand
          'clay-dark': '#5A371F', // Hover states
          tan: '#B98255',         // Light accent
          sand: '#F3E7DB',        // Pale background
          olive: '#556B2F',       // Secondary
          'olive-dark': '#3E5121',// Hover states
          sage: '#8CA66B',        // Soft green
          ochre: '#C58B2A',       // CTA/accent
          'ochre-dark': '#9A6A1E',// Hover states
        },
        // Warm neutral palette
        warm: {
          50: '#FAF7F2',   // Lightest - paper
          100: '#F3EEE6',  // Very light - parchment
          200: '#E7DED2',  // Light border
          300: '#D4C7B8',  // Border
          400: '#B9AA99',  // Muted text
          500: '#8B7D71',  // Secondary text
          600: '#6F6258',  // Body text
          700: '#564B43',  // Headings
          800: '#3D342E',  // Deep text
          900: '#2A231E',  // Darkest - near black
        },
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Roboto',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif',
        ],
      },
      boxShadow: {
        'soft': '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
        'card': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
        'lg': '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
        'xl': '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
  ],
}