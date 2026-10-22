/* Who built Vanguard3, for the About page. Fill these in; while name is
 * empty, the "About the builder" part of the page stays hidden. */

export const BUILDER: {
  name: string;
  /** One line under the name, e.g. "Student, Example School, Switzerland". */
  role: string;
  /** A few short paragraphs. */
  bio: string[];
  links: { label: string; href: string }[];
} = {
  name: "",
  role: "",
  bio: [],
  links: [],
};
