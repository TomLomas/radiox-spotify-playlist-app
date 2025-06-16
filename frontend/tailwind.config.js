/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
    "./public/index.html"
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          light: '#1DB954',
          dark: '#B266C8',
        },
        background: {
          light: '#FFFFFF',
          dark: '#212121',
        },
        card: {
          light: '#f4f4f9',
          dark: '#272727',
        },
        accent: {
          light: '#e8f5e9',
          dark: '#3a2a3d',
        },
        border: {
          light: '#e0e0e0',
          dark: '#333333',
        },
        disabled: '#bdbdbd',
      },
    },
  },
  plugins: [],
}

