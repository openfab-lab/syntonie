#!/usr/bin/env node
/**
 * TTL to Navigation JSON
 * Parses syntonie.ttl → navigation.json
 */

const fs = require('fs');
const path = require('path');

function parseTTL(ttlContent) {
  const triples = [];
  const lines = ttlContent.split('\n');

  let currentSubject = null;
  let buffer = '';

  for (let line of lines) {
    line = line.trim();

    // Skip comments, empty lines, and prefixes
    if (!line || line.startsWith('#') || line.startsWith('@')) continue;

    buffer += ' ' + line;

    // Check for statement end (period)
    if (line.endsWith('.')) {
      const statement = buffer.trim();
      parseStatement(statement, triples);
      buffer = '';
      currentSubject = null;
    }
  }

  return triples;
}

function parseStatement(stmt, triples) {
  // Remove trailing period
  stmt = stmt.replace(/\.$/, '').trim();

  // Split by semicolons (predicate ; predicate ; ...)
  const parts = stmt.split(/[;,]/);

  // First part: subject predicate object
  const firstPart = parts[0].trim();
  const firstMatch = firstPart.match(/^(\S+)\s+(\S+)\s+(.+)$/);

  if (!firstMatch) return;

  const [, subject, predicate, object] = firstMatch;
  triples.push({ subject, predicate, object: object.trim() });

  // Remaining parts: predicate object (reuse subject)
  for (let i = 1; i < parts.length; i++) {
    const part = parts[i].trim();
    if (!part) continue;

    const match = part.match(/^(\S+)\s+(.+)$/);
    if (match) {
      triples.push({ subject, predicate: match[1], object: match[2].trim() });
    }
  }
}

function extractValue(obj) {
  // "text"@lang
  let match = obj.match(/"([^"]+)"@(\w+)/);
  if (match) return { value: match[1], lang: match[2] };

  // "text"
  match = obj.match(/"([^"]+)"/);
  if (match) return { value: match[1], lang: 'fr' };

  // IRI: syntonie:something
  match = obj.match(/(\S+)/);
  if (match) return { value: match[1], lang: 'iri' };

  return { value: obj, lang: 'unknown' };
}

function buildNavigation(triples) {
  const recipes = {};
  const projects = {};
  const categories = {};

  // First pass: collect categories and projects
  for (const { subject, predicate, object } of triples) {
    const subId = subject.split(':')[1];

    if (subId?.startsWith('cat-')) {
      if (!categories[subId]) categories[subId] = { id: subId, label: {}, projects: [] };

      if (predicate.includes('title')) {
        const { value, lang } = extractValue(object);
        categories[subId].label[lang] = value;
      }
    }

    if (subId?.startsWith('proj-')) {
      if (!projects[subId]) projects[subId] = { id: subId, title: {}, description: {}, status: 'unknown' };

      if (predicate.includes('dcterms:title') || predicate === 'title') {
        const { value, lang } = extractValue(object);
        projects[subId].title[lang] = value;
      }
      if (predicate.includes('description')) {
        const { value, lang } = extractValue(object);
        projects[subId].description[lang] = value;
      }
      if (predicate.includes('status')) {
        const { value } = extractValue(object);
        projects[subId].status = value;
      }
    }
  }

  // Second pass: link categories to projects
  for (const { subject, predicate, object } of triples) {
    const subId = subject.split(':')[1];

    if (subId?.startsWith('cat-') && predicate.includes('containsProject')) {
      const projIds = object.split(',').map(p => p.trim().split(':')[1]);
      for (const projId of projIds) {
        if (projId && projId.startsWith('proj-')) {
          categories[subId].projects.push(projId);
        }
      }
    }
  }

  // Build recipes from categories
  for (const [catId, cat] of Object.entries(categories)) {
    const recipeId = catId.replace('cat-', '');

    if (!recipes[recipeId]) {
      recipes[recipeId] = {
        id: recipeId,
        label: cat.label,
        projects: []
      };
    }

    // Top 3 projects per recipe (active first)
    const sorted = [...new Set(cat.projects)]
      .map(id => ({ id, status: projects[id]?.status || 'unknown' }))
      .sort((a, b) => {
        const order = { active: 0, prototype: 1, archived: 2 };
        return (order[a.status] || 3) - (order[b.status] || 3);
      })
      .slice(0, 3);

    recipes[recipeId].projects = sorted.map(p => ({
      id: p.id,
      title: projects[p.id]?.title || {},
      description: projects[p.id]?.description || {},
      status: p.status
    }));
  }

  return { recipes, projects };
}

function main() {
  const ttlPath = path.join(__dirname, '..', 'data', 'syntonie.ttl');
  const outputPath = path.join(__dirname, '..', 'data', 'navigation.json');

  if (!fs.existsSync(ttlPath)) {
    console.error(`❌ TTL not found: ${ttlPath}`);
    process.exit(1);
  }

  console.log('📖 Reading TTL...');
  const ttlContent = fs.readFileSync(ttlPath, 'utf-8');

  console.log('🔍 Parsing...');
  const triples = parseTTL(ttlContent);
  console.log(`✓ ${triples.length} triples`);

  console.log('🏗️  Building navigation...');
  const nav = buildNavigation(triples);

  console.log('💾 Writing JSON...');
  fs.writeFileSync(outputPath, JSON.stringify(nav, null, 2));

  const recipeCount = Object.keys(nav.recipes).length;
  const projectCount = Object.keys(nav.projects).length;
  console.log(`✅ ${recipeCount} recipes × ${projectCount} projects`);
}

main();
