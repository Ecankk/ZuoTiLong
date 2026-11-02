/** 拼接 className，忽略空值。 */
export const cx = (...names: (string | false | null | undefined)[]) =>
  names.filter(Boolean).join(' ')
