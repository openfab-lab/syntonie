/**
 * Fog-of-war state machine
 * Pantry components: shelter-header, ownership-split, precedents-grid,
 *   project-allo-ia, project-invisible-play, value-imparfait,
 *   constellation-map, values-all, about-syntonie, mission, cta
 */

const RECIPES = {
  shelter:       ['shelter-header', 'ownership-split', 'precedents-grid', 'cta'],
  inclusion:     ['project-allo-ia', 'project-invisible-play', 'value-imparfait', 'cta'],
  constellation: ['constellation-map', 'precedents-grid', 'cta'],
  values:        ['values-all', 'shelter-header', 'cta'],
  about:         ['about-syntonie', 'mission', 'cta'],
}

const TRIGGERS = {
  shelter:       ['gouvernance', 'structure', 'asbl', 'légal', 'legal', 'cadre', 'financement', 'subvention', 'abri', 'appartenir', 'stabilité', 'erasmus'],
  inclusion:     ['neurodiversité', 'neurodiversite', 'inclusion', 'neuro', 'adhd', 'invisible', 'allo-ia', 'accessibilité', 'accessibilite', 'dys', 'autiste', 'hpi', 'hp', 'atypique'],
  constellation: ['fablab', 'making', 'builder', 'maker', 'bricoler', 'openfab', 'makerspace', 'hacker', 'fabriquer', 'atelier', 'espace', 'outils', 'constellation'],
  values:        ['open source', 'communs', 'indépendant', 'independant', 'imparfait', 'valeurs', 'open', 'liberté', 'liberte', 'prospectif'],
}

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
  document.querySelectorAll('.recipe-block').forEach(el => {
    el.hidden = true
    el.classList.remove('revealed')
  })
  if (!recipe) return
  const ids = RECIPES[recipe] || []
  ids.forEach(id => {
    const el = document.getElementById(id)
    if (el) {
      el.hidden = false
      el.classList.add('revealed')
    }
  })
}

// ── Autocomplete ───────────────────────────────────────────────

let topics = []
let activeIdx = -1

fetch(window.TOPICS_URL || '/js/topics.json')
  .then(r => r.json())
  .then(data => { topics = data })
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

// ── Init ───────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('fog-input')
  const suggestions = document.getElementById('fog-suggestions')
  if (!input) return

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
    }
  })

  // Close suggestions on outside click
  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !suggestions.contains(e.target)) {
      suggestions.hidden = true
    }
  })

  // Topic chips (data-recipe triggers direct reveal, bypassing text match)
  document.querySelectorAll('.topic-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const recipe = chip.dataset.recipe
      input.value = chip.textContent.trim()
      suggestions.hidden = true
      revealRecipe(recipe)
    })
  })
})
