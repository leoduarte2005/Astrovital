/**
 * Mock catalogue of the books in `data/books/` (folders and files in camelCase). The central does not
 * suggest books yet: these are the genres and preferences each crew member is given for now.
 * `title` and `author` are the original names; `file` is the path under `data/books/`.
 */
export const BOOK_GENRES = ['literaturaBrasileira', 'literaturaEstrangeira', 'filosofiaEEstrategia', 'didaticos'] as const
export type BookGenre = (typeof BOOK_GENRES)[number]

export interface Book {
  id: string
  genre: BookGenre
  title: string
  author: string
  file: string
}

export const BOOK_CATALOG: Book[] = [
  { id: 'aluisioAzevedoOCortico', genre: 'literaturaBrasileira', title: 'O Cortiço', author: 'Aluísio Azevedo', file: 'literaturaBrasileira/aluisioAzevedoOCortico.pdf' },
  { id: 'joseDeAlencarIracema', genre: 'literaturaBrasileira', title: 'Iracema', author: 'José de Alencar', file: 'literaturaBrasileira/joseDeAlencarIracema.pdf' },
  { id: 'machadoDeAssisDomCasmurroEdicaoAnotada', genre: 'literaturaBrasileira', title: 'Dom Casmurro (edição anotada)', author: 'Machado de Assis', file: 'literaturaBrasileira/machadoDeAssisDomCasmurroEdicaoAnotada.pdf' },
  { id: 'machadoDeAssisMemoriasPostumasDeBrasCubasEdicaoAnotada', genre: 'literaturaBrasileira', title: 'Memórias Póstumas de Brás Cubas (edição anotada)', author: 'Machado de Assis', file: 'literaturaBrasileira/machadoDeAssisMemoriasPostumasDeBrasCubasEdicaoAnotada.pdf' },
  { id: 'machadoDeAssisOAlienistaEdicaoCritica', genre: 'literaturaBrasileira', title: 'O Alienista (edição crítica)', author: 'Machado de Assis', file: 'literaturaBrasileira/machadoDeAssisOAlienistaEdicaoCritica.pdf' },
  { id: 'bramStokerDraculaEn', genre: 'literaturaEstrangeira', title: 'Dracula (EN)', author: 'Bram Stoker', file: 'literaturaEstrangeira/bramStokerDraculaEn.pdf' },
  { id: 'fScottFitzgeraldTheGreatGatsbyEn', genre: 'literaturaEstrangeira', title: 'The Great Gatsby (EN)', author: 'F. Scott Fitzgerald', file: 'literaturaEstrangeira/fScottFitzgeraldTheGreatGatsbyEn.pdf' },
  { id: 'franzKafkaAMetamorfose', genre: 'literaturaEstrangeira', title: 'A Metamorfose', author: 'Franz Kafka', file: 'literaturaEstrangeira/franzKafkaAMetamorfose.pdf' },
  { id: 'georgeOrwellARevolucaoDosBichos', genre: 'literaturaEstrangeira', title: 'A Revolução dos Bichos', author: 'George Orwell', file: 'literaturaEstrangeira/georgeOrwellARevolucaoDosBichos.pdf' },
  { id: 'hermanMelvilleMobyDickEn', genre: 'literaturaEstrangeira', title: 'Moby Dick (EN)', author: 'Herman Melville', file: 'literaturaEstrangeira/hermanMelvilleMobyDickEn.pdf' },
  { id: 'williamShakespeareHamlet', genre: 'literaturaEstrangeira', title: 'Hamlet', author: 'William Shakespeare', file: 'literaturaEstrangeira/williamShakespeareHamlet.pdf' },
  { id: 'marcusAureliusMeditationsEn', genre: 'filosofiaEEstrategia', title: 'Meditations (EN)', author: 'Marcus Aurelius', file: 'filosofiaEEstrategia/marcusAureliusMeditationsEn.pdf' },
  { id: 'plataoOBanqueteOuDoAmor', genre: 'filosofiaEEstrategia', title: 'O Banquete, ou Do Amor', author: 'Platão', file: 'filosofiaEEstrategia/plataoOBanqueteOuDoAmor.pdf' },
  { id: 'reneDescartesDiscourseOnTheMethodEn', genre: 'filosofiaEEstrategia', title: 'Discourse on the Method (EN)', author: 'René Descartes', file: 'filosofiaEEstrategia/reneDescartesDiscourseOnTheMethodEn.pdf' },
  { id: 'sunTzuAArteDaGuerra', genre: 'filosofiaEEstrategia', title: 'A Arte da Guerra', author: 'Sun Tzu', file: 'filosofiaEEstrategia/sunTzuAArteDaGuerra.pdf' },
  { id: 'siyavulaNaturalSciencesAndTechnologyGrade5AEn', genre: 'didaticos', title: 'Natural Sciences and Technology, Grade 5-A (EN)', author: 'Siyavula', file: 'didaticos/siyavulaNaturalSciencesAndTechnologyGrade5AEn.pdf' },
]

/** Genres each crew member likes, by the central's crew ids. Unknown crew see every genre. */
const PREFERENCES: Record<string, BookGenre[]> = {
  crew_001: ['literaturaEstrangeira', 'filosofiaEEstrategia'],
  crew_002: ['didaticos', 'literaturaBrasileira'],
  crew_003: ['didaticos', 'literaturaEstrangeira'],
}

/** Books suggested for a crew member, from the genres they like. */
export function suggestBooks(crewId: string): Book[] {
  const genres = PREFERENCES[crewId] ?? [...BOOK_GENRES]
  return BOOK_CATALOG.filter((book) => genres.includes(book.genre))
}

/**
 * Where a book's PDF is served from: the `books` folder next to the app (the `data/books` folder, served by the dev
 * and preview servers; see vite.config.ts). Relative, so it works under any host and the `./` base.
 */
export const bookFileUrl = (book: Book): string => `./books/${book.file}`
