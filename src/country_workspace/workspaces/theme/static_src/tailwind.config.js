/**
 * This is a minimal config.
 *
 * If you need the full config, get it from here:
 * https://unpkg.com/browse/tailwindcss@latest/stubs/defaultConfig.stub.js
 */
const { colors: defaultColors } = require('tailwindcss/defaultTheme')

module.exports = {
    darkMode: 'class',
    content: [
        /**
         * HTML. Paths to Django template files that will contain Tailwind CSS classes.
         */

        /*  Templates within theme app (<tailwind_app_name>/templates), e.g. base.html. */
        // '../templates/**/*.html',

        /*
         * Main templates directory of the project (BASE_DIR/templates).
         * Adjust the following line to match your project structure.
         */
        // '../../templates/**/*.html',

        /*
         * Templates in other django apps (BASE_DIR/<any_app_name>/templates).
         * Adjust the following line to match your project structure.
         */
        '../templates/**/*.html',
        '../**/templates/**/*.html',
        '../../**/templates/**/*.html',
        '../../../**/templates/**/*.html',
        '../../../../**/templates/**/*.html',
        /**
         * JS: If you use Tailwind CSS in JavaScript, uncomment the following lines and make sure
         * patterns match your project structure.
         */
        /* JS 1: Ignore any JavaScript in node_modules folder. */
        // '!../../**/node_modules',
        /* JS 2: Process all JavaScript files in the project. */
        // '../../**/*.js',

        /**
         * Python: If you use Tailwind CSS classes in Python, uncomment the following line
         * and make sure the pattern below matches your project structure.
         */
        // '../../**/*.py'
    ],
    theme: {
        extend: {
            width: {
                sidebar: '270px',
                'sidebar-collapsed': '55px',
            },
            colors: {
                // Logo blocks only. Use `primary` for accents.
                unicef: {
                    blue: '#00ADEF',
                },
                primary: {
                    DEFAULT: '#003C8F',
                    dark: '#003278',
                },
                secondary: '#233944',
                page: '#EEEEEE',
                label: 'rgba(37, 59, 70, 0.6)',
                value: '#253B46',
                ink: 'rgba(0, 0, 0, 0.87)',
                // HOPE's theme.ts hctPalette
                hct: {
                    orange: '#FC942A',
                    blue: '#D8E1EE',
                    darkerBlue: '#033D90',
                    green: '#10CB16',
                    gray: '#4E606A',
                    lightGray: '#D8D8D8',
                    lighterGray: '#C0C0C0',
                    lightestGray: '#FAFAFA',
                    red: '#EF4343',
                    brown: '#D9D1CE',
                    darkBrown: '#715247',
                    navyBlue: '#003C8F',
                    lightBlue: '#00ADEF',
                    teal: '#00897B',
                },
            },
        },
        screens: {
            'sm': '640px',
            // => @media (min-width: 640px) { ... }

            'md': '768px',
            // => @media (min-width: 768px) { ... }

            'lg': '1024px',
            // => @media (min-width: 1024px) { ... }

            'xl': '1280px',
            // => @media (min-width: 1280px) { ... }

            '2xl': '1536px',
            // => @media (min-width: 1536px) { ... }
        }
    },
    plugins: [
        /**
         * '@tailwindcss/forms' is the forms plugin that provides a minimal styling
         * for forms. If you don't like it or have own styling for forms,
         * comment the line below to disable '@tailwindcss/forms'.
         */
        require('@tailwindcss/forms'),
        require('@tailwindcss/typography'),
        require('@tailwindcss/line-clamp'),
        require('@tailwindcss/aspect-ratio'),
    ],
}
