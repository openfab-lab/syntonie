/**
 * Fog-of-war navigation — driven by navigation.json (from TTL)
 * Shows beachhead: top 2-3 projects per recipe
 */

// Static mapping: recipe key → DOM section IDs to reveal
const RECIPE_SECTIONS = {
  shelter:       ['shelter-header', 'ownership-split', 'precedents-grid', 'cta'],
  inclusion:     ['project-allo-ia', 'project-invisible-play', 'value-imparfait', 'cta'],
  constellation: ['constellation-map', 'precedents-grid', 'cta'],
  values:        ['values-all', 'shelter-header', 'cta'],
  about:         ['about-syntonie', 'mission', 'cta'],
  contact:       ['contact-block'],
}

let RECIPES = { ...RECIPE_SECTIONS }; // Start with static, may be enriched by navigation.json
let RECIPE_PROJECTS = {}; // Project metadata from navigation.json

// Trigger keywords → recipe mapping (will be enriched from TTL)
// ⚠️ COUPLING: every word here must also exist in static/js/topics.json,
// otherwise the keyword matches a recipe but never appears in the
// autocomplete dropdown. TRIGGERS = match logic; topics.json = suggestions.
let TRIGGERS = {
  shelter:       ['gouvernance', 'structure', 'asbl', 'légal', 'legal', 'cadre', 'financement', 'subvention', 'abri', 'appartenir', 'stabilité', 'erasmus'],
  inclusion:     ['neurodiversité', 'neurodiversite', 'inclusion', 'invisible', 'allo-ia', 'accessibilité', 'accessibilite', 'bruit', 'sensible', 'capteurs', 'sensoriel', 'espace', 'différemment', 'barrières', 'calme', 'silence'],
  constellation: ['fablab', 'making', 'builder', 'maker', 'bricoler', 'openfab', 'makerspace', 'hacker', 'fabriquer', 'atelier', 'espace', 'outils', 'constellation'],
  values:        ['open source', 'communs', 'indépendant', 'independant', 'imparfait', 'valeurs', 'open', 'liberté', 'liberte', 'prospectif'],
  contact:       ['contact', 'écrire', 'ecrire', 'message', 'rendez-vous', 'rdv', 'visite', 'visit', 'reach', 'email', 'joindre', 'parler', 'écris', 'ecris'],
}

const RECIPE_META = {
  shelter: {
    label: { fr: 'GOUVERNANCE', en: 'GOVERNANCE' },
    chips: [
      { label: 'financement',  recipe: 'shelter' },
      { label: 'ASBL',         recipe: 'shelter' },
      { label: 'autonomie',    recipe: 'shelter' },
      { label: 'inclusion',    recipe: 'inclusion' },
      { label: 'open source',  recipe: 'values' },
    ],
    related: ['values', 'inclusion'],
    action: { fr: 'Discutons de votre projet', en: "Let's talk about your project" },
  },
  inclusion: {
    label: { fr: 'INCLUSION', en: 'INCLUSION' },
    chips: [
      { label: 'neurodiversité', recipe: 'inclusion' },
      { label: 'atypique',       recipe: 'inclusion' },
      { label: 'allo-ia',        recipe: 'inclusion' },
      { label: 'fablab',         recipe: 'constellation' },
      { label: 'valeurs',        recipe: 'values' },
    ],
    related: ['values', 'constellation'],
    action: { fr: 'On se reconnaît ici', en: 'We see ourselves here' },
  },
  constellation: {
    label: { fr: 'ÉCOSYSTÈME', en: 'ECOSYSTEM' },
    chips: [
      { label: 'maker',       recipe: 'constellation' },
      { label: 'atelier',     recipe: 'constellation' },
      { label: 'bricoler',    recipe: 'constellation' },
      { label: 'gouvernance', recipe: 'shelter' },
      { label: 'communs',     recipe: 'values' },
    ],
    related: ['shelter', 'values'],
    action: { fr: 'Montrez-nous ce que vous fabriquez', en: 'Show us what you make' },
  },
  values: {
    label: { fr: 'NOS VALEURS', en: 'OUR VALUES' },
    chips: [
      { label: 'open source',  recipe: 'values' },
      { label: 'imparfait',    recipe: 'values' },
      { label: 'indépendant',  recipe: 'values' },
      { label: 'fablab',       recipe: 'constellation' },
      { label: 'gouvernance',  recipe: 'shelter' },
    ],
    related: ['constellation', 'shelter'],
    action: { fr: 'Ces valeurs résonnent ?', en: 'Do these values resonate?' },
  },
  about: {
    label: { fr: 'SYNTONIE', en: 'SYNTONIE' },
    chips: [
      { label: 'gouvernance',   recipe: 'shelter' },
      { label: 'neurodiversité',recipe: 'inclusion' },
      { label: 'fablab',        recipe: 'constellation' },
      { label: 'open source',   recipe: 'values' },
      { label: 'autonomie',     recipe: 'about' },
    ],
    related: ['shelter', 'constellation'],
    action: { fr: 'Prenons contact', en: 'Get in touch' },
  },
  contact: {
    label: { fr: 'CONTACT', en: 'CONTACT' },
    chips: [
      { label: 'gouvernance',   recipe: 'shelter' },
      { label: 'neurodiversité',recipe: 'inclusion' },
      { label: 'fablab',        recipe: 'constellation' },
      { label: 'open source',   recipe: 'values' },
      { label: 'autonomie',     recipe: 'about' },
    ],
    related: ['about', 'shelter'],
    action: { fr: 'On lit tout', en: 'We read everything' },
  },
}

let currentRecipe = null
let currentLang = localStorage.getItem('syntonie-lang') || 'fr'

function matchRecipe(input) {
  const q = input.toLowerCase().trim()
  if (!q) return null
  for (const [recipe, words] of Object.entries(TRIGGERS)) {
    if (words.some(w => q.includes(w))) return recipe
  }
  if (q.length > 2) return 'about'
  return null
}

function revealRecipe(recipe) {
  // ── Same-recipe guard: skip if already active ──
  if (currentRecipe === recipe) return
  currentRecipe = recipe

  // Sync URL hash so recipes are deep-linkable (e.g. /#contact)
  try {
    history.replaceState(null, '', recipe ? `#${recipe}` : location.pathname)
  } catch (_) {}

  // Lazy-init Tally when contact is first revealed
  if (recipe === 'contact' && typeof Tally !== 'undefined') {
    Tally.loadEmbeds()
  }

  // Hide all first (radical absence = display:none)
  document.querySelectorAll('.recipe-block').forEach(el => {
    el.hidden = true
    el.classList.remove('revealed', 'entering')
  })

  // Calculate centered padding and collapsed height based on content
  const fogZone = document.getElementById('fog-zone')
  if (fogZone) {
    const inputWrap = fogZone.querySelector('.fog-input-wrap')
    const topics = fogZone.querySelector('.fog-topics')

    if (inputWrap && topics) {
      if (recipe) {
        // Recipe active: calculate collapsed height for compact fog-zone
        const contentHeight = inputWrap.offsetHeight + 18 + topics.offsetHeight // +18 for gap
        const collapsedHeight = contentHeight + 20 + 60 // 20px top + 60px bottom padding
        fogZone.style.setProperty('--min-height-collapsed', `${collapsedHeight}px`)
      } else {
        // Reset: clear inline vars so CSS defaults (120px + justify-content:center) take over
        fogZone.style.removeProperty('--padding-centered')
        fogZone.style.removeProperty('--min-height-collapsed')
      }
    }

    fogZone.classList.toggle('has-recipe', !!recipe)
  }

  // Update keyword chips (responsive to current recipe)
  updateKeywordChips(recipe)

  // Update sidebar nav (responsive to current recipe)
  updateSidebarNav(recipe)

  if (!recipe) return

  // Reveal and animate
  const ids = RECIPES[recipe] || []
  ids.forEach((id, i) => {
    const el = document.getElementById(id)
    if (!el) return
    el.hidden = false
    el.classList.add('revealed')
    // Stagger: each block 80ms after previous
    el.style.setProperty('--delay', `${i * 0.08}s`)

    // Trigger animation on next frame (display:none → display:flex requires frame boundary)
    // Primary: double rAF
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.classList.add('entering')
      })
    })

    // Safari fallback: if animation didn't fire in 16ms, force it
    setTimeout(() => {
      if (!el.classList.contains('entering')) {
        el.classList.add('entering')
      }
    }, 16)
  })

}

// ── Autocomplete ───────────────────────────────────────────────

let topics = []
let activeIdx = -1

fetch(window.TOPICS_URL || '/js/topics.json')
  .then(r => r.json())
  .then(data => {
    topics = data
    // ── Sync check: warn if any TRIGGERS keyword is missing from topics.json ──
    // ⚠️ COUPLING: TRIGGERS = match logic; topics.json = autocomplete suggestions.
    // If a word is here but not there, it matches a recipe but never surfaces in the dropdown.
    const topicsLower = new Set(data.map(t => t.toLowerCase()))
    Object.entries(TRIGGERS).forEach(([recipe, words]) => {
      words.forEach(w => {
        if (!topicsLower.has(w.toLowerCase())) {
          console.warn(`⚠️ TRIGGERS/topics.json drift: "${w}" (${recipe}) is in TRIGGERS but missing from topics.json`)
        }
      })
    })
  })
  .catch(() => {})

function suggest(q) {
  const box = document.getElementById('fog-suggestions')
  if (!q || q.length < 2) { box.hidden = true; return }
  const matches = topics
    .filter(t => t.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 8)
  if (!matches.length) { box.hidden = true; return }
  box.innerHTML = matches
    .map(t => `<div class="fog-suggestion-item" role="option">${t}</div>`)
    .join('')
  box.hidden = false
  activeIdx = -1
  box.querySelectorAll('.fog-suggestion-item').forEach((item, i) => {
    item.addEventListener('mousedown', e => {
      e.preventDefault()
      applyTopic(item.textContent)
    })
  })
}

function applyTopic(text) {
  const input = document.getElementById('fog-input')
  input.value = text
  document.getElementById('fog-suggestions').hidden = true
  activeIdx = -1
  revealRecipe(matchRecipe(text))
}

function getCurrentLang() {
  return currentLang
}

function setLang(lang) {
  currentLang = lang
  localStorage.setItem('syntonie-lang', lang)
  document.documentElement.setAttribute('data-lang', lang)

  // Show/hide language spans
  document.querySelectorAll('.lang-fr').forEach(el => {
    el.style.display = lang === 'fr' ? '' : 'none'
  })
  document.querySelectorAll('.lang-en').forEach(el => {
    el.style.display = lang === 'en' ? '' : 'none'
  })

  // Update input placeholder
  const input = document.getElementById('fog-input')
  if (input) {
    const placeholderKey = `placeholder${lang.charAt(0).toUpperCase() + lang.slice(1)}`
    input.placeholder = input.dataset[placeholderKey] || input.placeholder
  }

  // Update lang toggle active state
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.textContent.toLowerCase() === lang)
  })

  // Refresh chips with updated language
  const recipe = currentRecipe
  updateKeywordChips(recipe)
  if (recipe) updateSidebarNav(recipe)
}

function updateKeywordChips(recipe) {
  const container = document.getElementById('fog-topics')
  if (!container) return

  const chips = recipe
    ? (RECIPE_META[recipe]?.chips || [])
    : [
        { label: 'gouvernance',   recipe: 'shelter' },
        { label: 'structure',     recipe: 'shelter' },
        { label: 'neurodiversité',recipe: 'inclusion' },
        { label: 'fablab',        recipe: 'constellation' },
        { label: 'making',        recipe: 'constellation' },
        { label: 'open source',   recipe: 'values' },
        { label: 'autonomie',     recipe: 'about' },
      ]

  container.innerHTML = chips.map(c =>
    `<button class="topic-chip" data-recipe="${c.recipe}">${c.label}</button>`
  ).join('')

  // Event delegation is already set up on the container in DOMContentLoaded
  // so re-binding is not needed — clicks will bubble up to parent listener
}

function updateSidebarNav(recipe) {
  const middle = document.getElementById('nav-middle')
  if (!middle) return

  if (!recipe) {
    middle.innerHTML = ''
    return
  }

  const meta = RECIPE_META[recipe]
  const lang = getCurrentLang()
  const label = meta?.label?.[lang] || recipe.toUpperCase()
  middle.innerHTML = `
    <span class="nav-item nav-item-recipe">
      <span class="nav-num">→</span>
      <span class="nav-recipe-label">${label}</span>
    </span>
  `
}

// ── Init ───────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  const input = document.getElementById('fog-input')
  const suggestions = document.getElementById('fog-suggestions')
  if (!input) return

  // Load navigation data from TTL
  try {
    const resp = await fetch(window.NAVIGATION_URL || '/data/navigation.json')
    const nav = await resp.json()
    RECIPE_PROJECTS = nav.projects || {}
    console.log(`✓ Loaded navigation.json (${Object.keys(RECIPE_PROJECTS).length} projects)`)
  } catch (err) {
    console.log('⚠️  Using static RECIPES/TRIGGERS')
  }

  // Typing
  input.addEventListener('input', () => {
    suggest(input.value)
    const recipe = matchRecipe(input.value)
    if (recipe) revealRecipe(recipe)
    else if (!input.value) revealRecipe(null)
  })

  // Keyboard navigation
  input.addEventListener('keydown', e => {
    const items = suggestions.querySelectorAll('.fog-suggestion-item')
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      activeIdx = Math.min(activeIdx + 1, items.length - 1)
      items.forEach((el, i) => el.classList.toggle('active', i === activeIdx))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      activeIdx = Math.max(activeIdx - 1, -1)
      items.forEach((el, i) => el.classList.toggle('active', i === activeIdx))
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      applyTopic(items[activeIdx].textContent)
    } else if (e.key === 'Escape') {
      suggestions.hidden = true
      activeIdx = -1
      input.value = ''
      revealRecipe(null)
    }
  })

  // Close suggestions on outside click
  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !suggestions.contains(e.target)) {
      suggestions.hidden = true
    }
  })

  // Topic chips: event delegation on parent (survives DOM rebuilds)
  const topicsContainer = document.getElementById('fog-topics')
  if (topicsContainer) {
    topicsContainer.addEventListener('click', (e) => {
      if (e.target.classList.contains('topic-chip')) {
        const recipe = e.target.dataset.recipe
        input.value = e.target.textContent.trim()
        suggestions.hidden = true
        revealRecipe(recipe)
      }
    })
  }

  // Recipe links anywhere in the page (data-recipe attribute)
  document.addEventListener('click', (e) => {
    const link = e.target.closest('[data-recipe]')
    if (link && !link.classList.contains('topic-chip')) {
      e.preventDefault()
      const recipe = link.dataset.recipe
      input.value = ''
      revealRecipe(recipe)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  })

  // Wire brand-reset and nav-accueil to clear recipe
  const brandReset = document.getElementById('brand-reset')
  if (brandReset) {
    brandReset.addEventListener('click', e => {
      e.preventDefault()
      input.value = ''
      revealRecipe(null)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    })
  }

  const navAccueil = document.getElementById('nav-accueil')
  if (navAccueil) {
    navAccueil.addEventListener('click', e => {
      e.preventDefault()
      input.value = ''
      revealRecipe(null)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    })
  }

  const navAbout = document.getElementById('nav-about')
  if (navAbout) {
    navAbout.addEventListener('click', e => {
      e.preventDefault()
      input.value = 'syntonie'
      revealRecipe('about')
    })
  }

  // Language toggle
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      setLang(btn.textContent.toLowerCase())
    })
  })

  // Initialize language on page load
  setLang(currentLang)

  // Deep-link support: if URL has a recipe hash (e.g. /#contact), auto-reveal
  const hash = window.location.hash.slice(1)
  if (hash && RECIPE_SECTIONS[hash]) {
    revealRecipe(hash)
  }
})
