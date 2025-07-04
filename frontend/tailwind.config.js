/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
    "./public/index.html"
  ],
  safelist: [
    'bg-purple-500',
    'bg-yellow-500',
    'bg-red-500',
    'bg-purple-600',
    'bg-gray-800',
    'bg-gray-700',
    'bg-gray-900',
    'text-white',
    'text-gray-300',
    'text-gray-400',
    'text-purple-400',
    'hover:bg-gray-700',
    'hover:bg-gray-600',
    'hover:bg-red-600',
    'hover:bg-purple-600',
    'rounded',
    'rounded-lg',
    'rounded-full',
    'shadow',
    'shadow-sm',
    'container',
    'min-h-screen',
    'flex',
    'items-center',
    'justify-center',
    'justify-between',
    'space-x-2',
    'space-x-4',
    'space-y-6',
    'grid',
    'grid-cols-1',
    'lg:grid-cols-2',
    'lg:grid-cols-3',
    'sm:grid-cols-2',
    'overflow-x-auto',
    'truncate',
    'font-semibold',
    'font-medium',
    'font-bold',
    'text-lg',
    'text-xl',
    'text-2xl',
    'text-sm',
    'text-xs',
    'mb-2',
    'mb-3',
    'mb-4',
    'mb-6',
    'mt-1',
    'mt-2',
    'mt-6',
    'mt-8',
    'p-4',
    'p-6',
    'px-4',
    'px-6',
    'py-2',
    'py-3',
    'py-4',
    'py-8',
    'w-3',
    'w-10',
    'w-12',
    'w-16',
    'h-3',
    'h-10',
    'h-12',
    'h-16',
    'min-w-0',
    'min-w-full',
    'divide-y',
    'divide-gray-600',
    'divide-gray-700',
    'uppercase',
    'tracking-wider',
    'transition-colors',
    'animate-spin',
  ],
  theme: {
    extend: {
      colors: {
        'background-light': '#ffffff',
        'background-dark': '#1a1a1a',
      },
    },
  },
  plugins: [],
  darkMode: 'class',
} 